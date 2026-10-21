"""
Background service that polls MZone API every 10 seconds to:
1. Update tracker positions in database
2. Check geofences automatically
3. Enable real-time alerts without manual refresh

TrackSolid tags are polled via the TrackSolid getMonitorInfo endpoint instead
of MZone, and their battery level is refreshed at the same interval.

Note: 10s poll interval is faster than the device hardware reporting frequency
(typically 30s-2min), but ensures we catch new positions as soon as the upstream
API's lastKnownPosition cache is refreshed.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import List
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import BLETag, User, HiveTagMembership, POITrackerLink, GeofenceAlert, PortalAlert
from app.models_admin import TagPackage
from app.services.mzone_service import MZoneService
from app.services.geofence_service import GeofenceService
from app.services.geocode_service import GeocodeService
from app.services.device_providers.tracksolid_provider import fetch_all_tracksolid_locations_open_api
from app.services import portal_alert_service

logger = logging.getLogger(__name__)

class LocationPollerService:
    def __init__(self):
        self.mzone_service = MZoneService()
        # Use FROM_EMAIL env var for tenant-aware contact, fallback to neutral default
        contact_email = os.getenv("FROM_EMAIL", "contact@pinplot.me")
        # GeocodeService defaults to MapTiler (reads MAPTILER_API_KEY from env)
        self.geocode_service = GeocodeService(
            threshold_metres=500,
            user_agent=f"PinPlot/1.0 ({contact_email})"
        )
        self.running = False
        self.poll_interval = 10  # seconds (Series 1 / MZone cadence)
        # TrackSolid (Series 2) is polled much less often:
        # - Series 2 device hardware reports every ~5-10 min, so faster polling
        #   yields no new data anyway.
        # - TrackSolid's WAF will IP-ban hosts that hit its endpoints every
        #   10s × N tags (~43k req/day for 5 tags). Once banned, every call
        #   stalls until the connect timeout, eating workers + causing OOM.
        # - The token itself is reused for ~59 min (see TrackSolidTokenManager)
        #   so this only affects the per-tag getMonitorInfo calls.
        self.series2_poll_interval = 600  # seconds (10 minutes)
        self._last_series2_poll_at: datetime | None = None
        
    async def start(self):
        """Start the background polling service"""
        self.running = True
        logger.info(
            f"🚀 Location Poller Service started — Series 1 every {self.poll_interval}s, "
            f"Series 2 (TrackSolid) every {self.series2_poll_interval}s"
        )
        
        while self.running:
            try:
                await self._poll_locations()
            except Exception as e:
                logger.error(f"❌ Error in location polling cycle: {str(e)}")
            
            # Wait before next poll
            await asyncio.sleep(self.poll_interval)
    
    def stop(self):
        """Stop the background polling service"""
        self.running = False
        logger.info("🛑 Location Poller Service stopped")
    
    async def _poll_locations(self):
        """Poll all active trackers and check geofences"""
        db = SessionLocal()
        try:
            now_utc = datetime.utcnow()

            # ── Auto-delete: hard-delete tags whose expiry + auto_delete_days has passed ──
            expired_tags = (
                db.query(BLETag)
                .filter(BLETag.expiry_date.isnot(None), BLETag.package_id.isnot(None))
                .all()
            )
            for tag in expired_tags:
                if tag.expiry_date is None:
                    continue
                pkg = db.query(TagPackage).filter(TagPackage.id == str(tag.package_id)).first()
                if pkg and pkg.auto_delete_days is not None:
                    delete_after = tag.expiry_date.replace(tzinfo=None) + timedelta(days=pkg.auto_delete_days)
                    if delete_after < now_utc:
                        logger.info("🗑️  Auto-deleting tag IMEI %s (expired %s days ago)", tag.imei, pkg.auto_delete_days)
                        # Clean dependent rows first to avoid FK violations.
                        # Some legacy rows still reference expired tags.
                        db.query(HiveTagMembership).filter(HiveTagMembership.tag_id == tag.id).delete(synchronize_session=False)
                        db.query(POITrackerLink).filter(POITrackerLink.tracker_id == tag.id).delete(synchronize_session=False)
                        db.query(GeofenceAlert).filter(GeofenceAlert.tracker_id == tag.id).delete(synchronize_session=False)
                        db.query(PortalAlert).filter(PortalAlert.tag_id == tag.id).update(
                            {PortalAlert.tag_id: None},
                            synchronize_session=False,
                        )
                        db.delete(tag)
            db.commit()

            # Get all active trackers across all users
            trackers = db.query(BLETag).filter(
                BLETag.is_active == True,
                or_(BLETag.tag_type.is_(None), BLETag.tag_type.notin_(("series3", "series_3"))),
            ).all()

            # ── Expiry enforcement: skip tags whose package has expired ──
            def _is_expired(tag: BLETag) -> bool:
                if tag.expiry_date is None:
                    return False
                return tag.expiry_date.replace(tzinfo=None) < now_utc

            live_trackers = [t for t in trackers if not _is_expired(t)]
            expired_count = len(trackers) - len(live_trackers)
            if expired_count:
                logger.info("⏱️  Skipping %d tracker(s) with expired packages", expired_count)

            if not live_trackers:
                logger.debug("No active trackers to poll")
                return

            # Split by provider type.
            # Accept both the canonical DB names ('scope', 'tracksolid', 'ble', 'hubble') and
            # the Flutter app's series aliases ('series1', 'series2', etc.) so that
            # tags added by any client version are polled correctly.
            _SERIES2_KEYS = {"series2", "tracksolid"}
            _SERIES1_KEYS = {"series1", "scope"}
            _SERIES4_KEYS = {"series4", "ble"}  # Series 4 (DX-Smart indoor BLE)
            _SERIES5_KEYS = {"series5", "hubble"}  # Series 5 (Hubble Platform BLE)
            _PUSH_KEYS = {"teltonika"}  # DataProfiler: events arrive via the GPRS listener, nothing to poll

            def _tag_key(t) -> str:
                return (t.tag_type or "series1").lower().replace("_", "").replace("-", "")

            series2_trackers = [t for t in live_trackers if _tag_key(t) in _SERIES2_KEYS]
            series1_trackers = [t for t in live_trackers if _tag_key(t) in _SERIES1_KEYS]
            series4_trackers = [t for t in live_trackers if _tag_key(t) in _SERIES4_KEYS]
            series5_trackers = [t for t in live_trackers if _tag_key(t) in _SERIES5_KEYS]
            unknown_trackers = [t for t in live_trackers
                                   if _tag_key(t) not in _SERIES2_KEYS | _SERIES1_KEYS | _SERIES4_KEYS | _SERIES5_KEYS | _PUSH_KEYS]
            for t in unknown_trackers:
                logger.warning("⚠️  Tracker IMEI %s has unrecognised tag_type '%s' — skipping", t.imei, t.tag_type)

            # Series 4 (BLE indoor) and Series 5 (Hubble Platform BLE) are not GPS-enabled
            # Series 4 reports positions via mobile app scans
            # Series 5 reports positions via Hubble Platform gateway network
            if series4_trackers:
                logger.debug("📍 Series 4 (BLE indoor): %d tags (position via mobile app scans)", len(series4_trackers))
            if series5_trackers:
                logger.debug("📍 Series 5 (Hubble Platform): %d tags", len(series5_trackers))

            updated_count = 0

            # ── Poll Series 2 tags (TrackSolid, every 10 min) ──────────────
            # Throttled separately from the main loop to avoid hammering the
            # TrackSolid API (see __init__ for rationale).
            now_dt = datetime.utcnow()
            series2_due = (
                self._last_series2_poll_at is None
                or (now_dt - self._last_series2_poll_at).total_seconds()
                   >= self.series2_poll_interval
            )
            if series2_trackers and series2_due:
                self._last_series2_poll_at = now_dt
                # ONE API call for all devices via jimi.user.device.location.list
                imeis = [t.imei for t in series2_trackers]
                try:
                    ts_locations = await fetch_all_tracksolid_locations_open_api(imeis, db_session=db)
                except Exception as exc:
                    logger.error("Series 2 location fetch failed: %s", exc)
                    ts_locations = {}

                # If the whole batch was skipped (WAF block, backoff, outage)
                # don't emit 110× per-IMEI WARN spam — the provider already
                # logged a single batch-level error.
                if not ts_locations:
                    series2_trackers = []

                for tracker in series2_trackers:
                    loc = ts_locations.get(tracker.imei.strip())
                    if not loc:
                        logger.warning("⚠️  Series 2 IMEI %s not in location response", tracker.imei)
                        continue
                    if loc.latitude == 0.0 and loc.longitude == 0.0:
                        logger.warning("⚠️  Series 2 IMEI %s has no GPS fix", tracker.imei)
                        continue

                    tracker.latitude = str(loc.latitude)
                    tracker.longitude = str(loc.longitude)
                    # Always update location_description, even if null/empty
                    # This clears stale addresses when TrackSolid stops providing them
                    tracker.location_description = loc.address
                    
                    # If TrackSolid didn't provide an address, use reverse geocoding
                    # (only makes API call if device moved >500m since last geocode)
                    if not tracker.location_description:
                        try:
                            geo_result = self.geocode_service.reverse_geocode(
                                device_imei=tracker.imei,
                                lat=loc.latitude,
                                lng=loc.longitude
                            )
                            tracker.location_description = geo_result["address"]
                            if geo_result.get("cached"):
                                logger.debug("📍 Series 2 IMEI %s: cached geocode (moved %.1fm)", 
                                           tracker.imei, geo_result.get("distance_moved", 0))
                            else:
                                logger.info("🌍 Series 2 IMEI %s: reverse geocoded to '%s'", 
                                          tracker.imei, geo_result["address"])
                        except Exception as exc:
                            logger.error("❌ Geocoding error for IMEI %s: %s", tracker.imei, exc)
                    
                    # Use the actual GPS fix time from the device; fall back to
                    # poll time only if the API didn't return a timestamp.
                    tracker.last_seen = loc.gps_time or datetime.utcnow()

                    # Set activation_date on first GPS fix and (re)calculate expiry
                    if tracker.activation_date is None:
                        tracker.activation_date = datetime.utcnow()
                        if tracker.package_id:
                            pkg = db.query(TagPackage).filter(TagPackage.id == str(tracker.package_id)).first()
                            if pkg:
                                tracker.expiry_date = tracker.activation_date + timedelta(days=pkg.validity_days)
                                logger.info("📅 Tag %s activated — expiry set to %s", tracker.imei, tracker.expiry_date)

                    # Refresh battery level and attributes dict if available
                    if loc.battery_level is not None:
                        tracker.battery_level = loc.battery_level
                        attrs = tracker.attributes or {}
                        attrs["Battery"] = {
                            "value": f"{loc.battery_level}%",
                            "show_on_map": True,
                        }
                        tracker.attributes = attrs

                    # Check geofences
                    user = db.query(User).filter(User.id == tracker.user_id).first()
                    if user:
                        try:
                            GeofenceService.check_geofences_for_tracker(
                                db,
                                str(tracker.id),
                                loc.latitude,
                                loc.longitude,
                                str(user.id),
                            )
                        except Exception as exc:
                            logger.error("❌ Geofence check error for tracker %s: %s", tracker.id, exc)

                    updated_count += 1

            # ── Series 5 / Hubble Platform tags ────────────────────────────
            # NOTE: Series 5 tags are updated via webhook (real-time push from Hubble)
            # API polling disabled to avoid overwriting fresh webhook data with stale page 1 results
            # See routes_webhooks.py for webhook implementation
            if series5_trackers:
                logger.info(f"📡 Skipping {len(series5_trackers)} Series 5 / Hubble tags (webhook-only mode)")
                # Webhook handles: position, last_seen, sensor data, geofences, geocoding
                # No API polling needed - webhooks provide real-time updates

            # ── Poll Series 1 / MZone tags ────────────────────────────────────
            if series1_trackers:
                imeis = [tracker.imei for tracker in series1_trackers]
                logger.info(f"📡 Polling {len(imeis)} Series 1 / MZone trackers")
                vehicles = self.mzone_service.get_vehicles_with_locations(imeis)

                vehicle_map = {}
                for v in vehicles:
                    reg = v.get('registration', '')
                    unit_desc = v.get('unit_Description', '')
                    for imei in imeis:
                        if reg == imei or unit_desc == imei:
                            vehicle_map[imei] = v
                            break

                logger.info(f"🗺️  Built vehicle map with {len(vehicle_map)} entries for {len(imeis)} Series 1 trackers")

                for tracker in series1_trackers:
                    vehicle = vehicle_map.get(tracker.imei)
                    if not vehicle:
                        logger.warning(f"⚠️  No vehicle data found for tracker IMEI: {tracker.imei}")
                        continue

                    position = vehicle.get('lastKnownPosition', {})
                    if not position or not position.get('latitude') or not position.get('longitude'):
                        logger.warning(f"⚠️  No location data for tracker IMEI: {tracker.imei}")
                        continue

                    tracker.latitude = str(position.get('latitude'))
                    tracker.longitude = str(position.get('longitude'))
                    tracker.location_description = position.get('locationDescription')
                    # MZone returns utcTimestamp = when the device last reported a fix.
                    # Parse it so last_seen shows real GPS age, not poll time.
                    _mzone_ts = position.get('utcTimestamp')
                    if _mzone_ts:
                        try:
                            tracker.last_seen = datetime.strptime(
                                str(_mzone_ts).replace('Z', ''),
                                '%Y-%m-%dT%H:%M:%S'
                            )
                        except (ValueError, TypeError):
                            try:
                                tracker.last_seen = datetime.fromisoformat(
                                    str(_mzone_ts).rstrip('Z')
                                )
                            except (ValueError, TypeError):
                                tracker.last_seen = datetime.utcnow()
                    else:
                        tracker.last_seen = datetime.utcnow()

                    # Set activation_date on first GPS fix and (re)calculate expiry
                    if tracker.activation_date is None:
                        tracker.activation_date = datetime.utcnow()
                        if tracker.package_id:
                            pkg = db.query(TagPackage).filter(TagPackage.id == str(tracker.package_id)).first()
                            if pkg:
                                tracker.expiry_date = tracker.activation_date + timedelta(days=pkg.validity_days)
                                logger.info("📅 Tag %s activated — expiry set to %s", tracker.imei, tracker.expiry_date)

                    mzone_vehicle_id = vehicle.get('id')
                    if mzone_vehicle_id and tracker.mzone_vehicle_id != mzone_vehicle_id:
                        tracker.mzone_vehicle_id = mzone_vehicle_id
                        logger.debug(f"💾 Cached MZone vehicle_Id {mzone_vehicle_id} for IMEI {tracker.imei}")

                    description = vehicle.get('description')
                    # Only auto-fill description from MZone if the tag has no description
                    # at all. Once any description exists (set by user via portal OR
                    # previously set by the poller), never overwrite it — this prevents
                    # MZone from undoing changes made on the Customer Portal.
                    # The _user_named flag provides belt-and-suspenders for newly edited tags.
                    _user_named = (tracker.attributes or {}).get('_user_named', False)
                    if description and not _user_named and not tracker.description:
                        tracker.description = description
                        tracker.updated_at = datetime.utcnow()

                    user = db.query(User).filter(User.id == tracker.user_id).first()
                    if not user:
                        continue

                    try:
                        GeofenceService.check_geofences_for_tracker(
                            db,
                            str(tracker.id),
                            position.get('latitude'),
                            position.get('longitude'),
                            str(user.id)
                        )
                    except Exception as e:
                        logger.error(f"❌ Error checking geofences for tracker {tracker.id}: {str(e)}")

                    updated_count += 1

            # Commit all updates
            db.commit()
            logger.info(f"✅ Updated {updated_count} tracker positions and checked geofences "
                        f"({len(series2_trackers)} Series 2 / TrackSolid, {len(series1_trackers)} Series 1 / MZone, "
                        f"{len(series4_trackers)} Series 4 / BLE Indoor, "
                        f"{len(series5_trackers)} Series 5 / Hubble webhook-only)")

            # ── Generate battery-low and offline portal alerts ─────────────
            alert_count = 0
            for tracker in live_trackers:
                try:
                    if portal_alert_service.check_battery_alert(db, tracker):
                        alert_count += 1
                    if portal_alert_service.check_offline_alert(db, tracker):
                        alert_count += 1
                except Exception as exc:
                    logger.error("Alert check error for tracker %s: %s", tracker.imei, exc)
            if alert_count:
                db.commit()
                logger.info("🔔 Generated %d portal alert(s) this cycle", alert_count)

            # ── Purge portal alerts older than 7 days ─────────────────────
            try:
                purged = portal_alert_service.purge_old_alerts(db)
                if purged:
                    db.commit()
            except Exception as exc:
                logger.error("Alert purge error: %s", exc)

        except Exception as e:
            logger.error(f"❌ Error in _poll_locations: {str(e)}")
            db.rollback()
        finally:
            db.close()


# Global instance
location_poller = LocationPollerService()
