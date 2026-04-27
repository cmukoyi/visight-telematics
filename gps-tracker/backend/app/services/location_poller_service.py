"""
Background service that polls MZone API every 60 seconds to:
1. Update tracker positions in database
2. Check geofences automatically
3. Enable real-time alerts without manual refresh

TrackSolid tags are polled via the TrackSolid getMonitorInfo endpoint instead
of MZone, and their battery level is refreshed at the same interval.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import BLETag, User
from app.models_admin import TagPackage
from app.services.mzone_service import MZoneService
from app.services.geofence_service import GeofenceService
from app.services.device_providers.tracksolid_provider import fetch_all_tracksolid_locations

logger = logging.getLogger(__name__)

class LocationPollerService:
    def __init__(self):
        self.mzone_service = MZoneService()
        self.running = False
        self.poll_interval = 60  # seconds
        
    async def start(self):
        """Start the background polling service"""
        self.running = True
        logger.info("🚀 Location Poller Service started - polling every 60 seconds")
        
        while self.running:
            try:
                await self._poll_locations()
            except Exception as e:
                logger.error(f"❌ Error in location polling cycle: {str(e)}")
            
            # Wait 60 seconds before next poll
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
                        db.delete(tag)
            db.commit()

            # Get all active trackers across all users
            trackers = db.query(BLETag).filter(BLETag.is_active == True).all()

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

            # Split by provider type — only known types are routed; unknowns are logged and skipped
            series2_trackers = [t for t in live_trackers if (t.tag_type or "").lower() == "series2"]
            series1_trackers = [t for t in live_trackers if (t.tag_type or "series1").lower() == "series1"]
            unknown_trackers = [t for t in live_trackers
                                   if (t.tag_type or "series1").lower() not in ("series2", "series1")]
            for t in unknown_trackers:
                logger.warning("⚠️  Tracker IMEI %s has unrecognised tag_type '%s' — skipping", t.imei, t.tag_type)

            updated_count = 0

            # ── Poll Series 2 tags ──────────────────────────────────────
            if series2_trackers:
                # Parallel per-IMEI calls to getMonitorInfo (V3 Bearer JWT)
                imeis = [t.imei for t in series2_trackers]
                try:
                    ts_locations = await fetch_all_tracksolid_locations(imeis)
                except Exception as exc:
                    logger.error("Series 2 location fetch failed: %s", exc)
                    ts_locations = {}

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
                    if loc.address:
                        tracker.location_description = loc.address
                    tracker.last_seen = datetime.utcnow()

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

            # ── Poll MZone tags ───────────────────────────────────────────
            if mzone_trackers:
                imeis = [tracker.imei for tracker in mzone_trackers]
                logger.info(f"📡 Polling {len(imeis)} MZone trackers")
                vehicles = self.mzone_service.get_vehicles_with_locations(imeis)

                vehicle_map = {}
                for v in vehicles:
                    reg = v.get('registration', '')
                    unit_desc = v.get('unit_Description', '')
                    for imei in imeis:
                        if reg == imei or unit_desc == imei:
                            vehicle_map[imei] = v
                            break

                logger.info(f"🗺️  Built vehicle map with {len(vehicle_map)} entries for {len(imeis)} MZone trackers")

                for tracker in mzone_trackers:
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
                    if description and tracker.description != description:
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
                        f"({len(tracksolid_trackers)} TrackSolid, {len(mzone_trackers)} MZone)")
            
        except Exception as e:
            logger.error(f"❌ Error in _poll_locations: {str(e)}")
            db.rollback()
        finally:
            db.close()


# Global instance
location_poller = LocationPollerService()
