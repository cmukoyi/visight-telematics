"""
Geofence monitoring service for POI entry/exit detection
"""
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models import POI, BLETag, POITrackerLink, GeofenceAlert, GeofenceEventType, GeofenceState, User, POIType
from app.services.email_service import EmailService
import math
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


class GeofenceService:
    """Service for monitoring geofences and generating entry/exit alerts"""
    
    @staticmethod
    def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate distance between two coordinates using Haversine formula
        Returns distance in meters
        """
        R = 6371000  # Earth's radius in meters
        
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)
        
        a = (math.sin(delta_lat / 2) ** 2 +
             math.cos(lat1_rad) * math.cos(lat2_rad) *
             math.sin(delta_lon / 2) ** 2)
        c = 2 * math.asin(math.sqrt(a))
        
        distance = R * c
        return distance
    
    @staticmethod
    def is_inside_geofence(
        lat: float, lon: float, 
        poi_lat: float, poi_lon: float, 
        radius: float
    ) -> bool:
        """Check if coordinates are inside a geofence"""
        distance = GeofenceService.calculate_distance(lat, lon, poi_lat, poi_lon)
        return distance <= radius
    
    @staticmethod
    def _get_last_alert_type(
        db: Session,
        tracker_id: str
    ) -> Optional[GeofenceEventType]:
        """
        Return the event_type of the most recently generated alert for this tracker
        across ALL POIs, or None if no alerts exist yet.
        Used to enforce the global EXIT↔ENTRY alternation rule.
        """
        last = (
            db.query(GeofenceAlert)
            .filter(GeofenceAlert.tracker_id == tracker_id)
            .order_by(GeofenceAlert.created_at.desc())
            .first()
        )
        return last.event_type if last else None

    @staticmethod
    def check_geofences_for_tracker(
        db: Session,
        tracker_id: str,
        current_lat: float,
        current_lon: float,
        user_id: str
    ) -> List[GeofenceAlert]:
        """
        Check all armed POIs for a tracker and generate alerts if needed
        Returns list of generated alerts
        """
        # Get all armed POIs for this tracker.
        # with_for_update() acquires a row-level lock so concurrent calls
        # (e.g. background poller + manual refresh) cannot read stale state
        # and each generate the same alert simultaneously.
        armed_links = db.query(POITrackerLink).filter(
            and_(
                POITrackerLink.tracker_id == tracker_id,
                POITrackerLink.is_armed == True
            )
        ).with_for_update().all()
        
        if not armed_links:
            return []
        
        generated_alerts = []

        # Seed the global last alert type from DB so the pairing rule is enforced
        # across calls and across different POIs within the same call.
        # Rule: EXIT must be followed by ENTRY and vice-versa. Two consecutive alerts
        # of the same type (e.g. ENTRY then ENTRY for different POIs) are suppressed.
        last_alert_type: Optional[GeofenceEventType] = GeofenceService._get_last_alert_type(
            db, tracker_id
        )

        for link in armed_links:
            poi = db.query(POI).filter(
                and_(
                    POI.id == link.poi_id,
                    POI.is_active == True
                )
            ).first()
            
            if not poi:
                continue
            
            # Handle different POI types
            if poi.poi_type == 'single':
                # Single location POI - monitor entry/exit at origin
                alerts = GeofenceService._check_single_poi(
                    db, poi, tracker_id, user_id, current_lat, current_lon,
                    last_global_event_type=last_alert_type
                )
                generated_alerts.extend(alerts)
            
            elif poi.poi_type == 'route':
                # Delivery route - monitor exit from origin and entry to destination
                alerts = GeofenceService._check_route_poi(
                    db, poi, tracker_id, user_id, current_lat, current_lon,
                    last_global_event_type=last_alert_type
                )
                generated_alerts.extend(alerts)

            # Advance the global sentinel so the NEXT POI in this same call
            # also sees the correct last event type (even before the DB commit).
            if alerts:
                last_alert_type = alerts[-1].event_type

        if generated_alerts:
            db.commit()
        
        return generated_alerts
    
    @staticmethod
    def _check_single_poi(
        db: Session,
        poi: POI,
        tracker_id: str,
        user_id: str,
        current_lat: float,
        current_lon: float,
        last_global_event_type: Optional[GeofenceEventType] = None
    ) -> List[GeofenceAlert]:
        """
        Check single location POI for entry/exit events using STRICT PAIRING logic.

        Per-POI Strict Pairing Rules:
        - If last_known_state == INSIDE  → only alert on EXIT  (tracker leaves)
        - If last_known_state == OUTSIDE → only alert on ENTRY (tracker enters)
        - If last_known_state == UNKNOWN → update state but DO NOT alert

        Global Pairing Rule (enforced via last_global_event_type):
        - Alerts must strictly alternate EXIT ↔ ENTRY across ALL POIs.
        - A second consecutive EXIT or ENTRY is suppressed regardless of per-POI state.
        """
        alerts = []

        # Get the POI-tracker link with a row-level lock.
        # This is the critical guard against the race condition where two concurrent
        # executions both read last_known_state before either commits the update,
        # causing identical alerts to fire within milliseconds of each other.
        link = db.query(POITrackerLink).filter(
            and_(
                POITrackerLink.poi_id == poi.id,
                POITrackerLink.tracker_id == tracker_id,
                POITrackerLink.is_armed == True
            )
        ).with_for_update().first()
        
        if not link:
            logger.warning(f"No armed link found for POI {poi.id} and tracker {tracker_id}")
            return alerts
        
        # Determine current position state
        is_inside = GeofenceService.is_inside_geofence(
            current_lat, current_lon,
            poi.latitude, poi.longitude,
            poi.radius
        )
        
        current_state = GeofenceState.INSIDE if is_inside else GeofenceState.OUTSIDE
        last_state = link.last_known_state
        
        # Strict pairing logic - only alert on expected transitions
        should_alert = False
        event_type = None
        
        if last_state == GeofenceState.UNKNOWN:
            # State is unknown (GPS unavailable at arm time)
            # Update to current state but DO NOT generate alert
            logger.info(f"Resolving unknown state for {poi.name}, tracker {tracker_id}: now {current_state.value}")
            
        elif last_state == GeofenceState.INSIDE and current_state == GeofenceState.OUTSIDE:
            # Expected transition: INSIDE → EXIT
            should_alert = True
            event_type = GeofenceEventType.EXIT
            logger.info(f"STRICT PAIR: {poi.name}, tracker {tracker_id}: INSIDE → EXIT (alert)")
            
        elif last_state == GeofenceState.OUTSIDE and current_state == GeofenceState.INSIDE:
            # Expected transition: OUTSIDE → ENTRY
            should_alert = True
            event_type = GeofenceEventType.ENTRY
            logger.info(f"STRICT PAIR: {poi.name}, tracker {tracker_id}: OUTSIDE → ENTRY (alert)")
            
        elif last_state == GeofenceState.INSIDE and current_state == GeofenceState.INSIDE:
            # Still inside - no alert (waiting for EXIT)
            logger.debug(f"No change for {poi.name}, tracker {tracker_id}: still INSIDE (waiting for EXIT)")
            
        elif last_state == GeofenceState.OUTSIDE and current_state == GeofenceState.OUTSIDE:
            # Still outside - no alert (waiting for ENTRY)
            logger.debug(f"No change for {poi.name}, tracker {tracker_id}: still OUTSIDE (waiting for ENTRY)")

        # Global pairing guard: EXIT must follow ENTRY and ENTRY must follow EXIT
        # across ALL POIs for this tracker.  Suppress any alert that would produce
        # two consecutive events of the same type.
        if should_alert and event_type and last_global_event_type is not None:
            if event_type == last_global_event_type:
                logger.warning(
                    f"GLOBAL PAIR GUARD: Suppressing {event_type.value} for '{poi.name}' / "
                    f"tracker {tracker_id} — last global alert was also "
                    f"{last_global_event_type.value}. Alerts must alternate EXIT ↔ ENTRY."
                )
                should_alert = False
                event_type = None

        # Handle UNKNOWN state: update to current state, no alert, no race guard needed
        if last_state == GeofenceState.UNKNOWN:
            link.last_known_state = current_state
            link.last_state_check = datetime.now(timezone.utc)
            db.add(link)

        # Generate alert ONLY if strict pair condition met.
        # IMPORTANT: db.refresh() must come BEFORE we write link.last_known_state — if the
        # refresh happens after the in-memory update it resets our change back to the DB
        # value (pre-commit), so the state never gets saved and every subsequent check fires
        # another alert for the same transition (the "36 exits" bug).
        elif should_alert and event_type:
            # Re-read state from DB — race guard: if a concurrent transaction already
            # advanced the state, this transition is no longer valid.
            db.refresh(link)
            if link.last_known_state != last_state:
                logger.warning(
                    f"RACE GUARD: state changed under lock for '{poi.name}' / tracker {tracker_id}. "
                    f"Was {last_state.value}, now {link.last_known_state.value}. Skipping alert."
                )
                return alerts

            # Update state AFTER the refresh so the refresh cannot wipe out our change.
            # This is what persists the new state (e.g. INSIDE→OUTSIDE) to the DB on commit,
            # preventing the same transition from being re-detected on the next call.
            link.last_known_state = current_state
            link.last_state_check = datetime.now(timezone.utc)
            db.add(link)

            alert = GeofenceAlert(
                poi_id=poi.id,
                tracker_id=tracker_id,
                user_id=user_id,
                event_type=event_type,
                latitude=current_lat,
                longitude=current_lon,
                is_read=False
            )
            db.add(alert)
            alerts.append(alert)
            
            logger.info(
                f"✅ ALERT GENERATED: tracker {event_type.value} {poi.name} (strict pairing)"
            )
            
            # Send email alert
            GeofenceService._send_email_alert(
                db, user_id, tracker_id, poi, event_type, current_lat, current_lon
            )
        
        return alerts
    
    @staticmethod
    def _check_route_poi(
        db: Session,
        poi: POI,
        tracker_id: str,
        user_id: str,
        current_lat: float,
        current_lon: float,
        last_global_event_type: Optional[GeofenceEventType] = None
    ) -> List[GeofenceAlert]:
        """Check delivery route POI for origin exit and destination entry"""
        alerts = []
        
        if not poi.destination_latitude or not poi.destination_longitude:
            logger.warning(f"Route POI {poi.id} missing destination coordinates")
            return alerts
        
        # Check origin (FROM) geofence - we care about EXITS
        is_at_origin = GeofenceService.is_inside_geofence(
            current_lat, current_lon,
            poi.latitude, poi.longitude,
            poi.radius
        )
        
        # Check destination (TO) geofence - we care about ENTRIES
        is_at_destination = GeofenceService.is_inside_geofence(
            current_lat, current_lon,
            poi.destination_latitude, poi.destination_longitude,
            poi.destination_radius or 150.0
        )
        
        # Get last two alerts for this route
        last_alerts = db.query(GeofenceAlert).filter(
            and_(
                GeofenceAlert.poi_id == poi.id,
                GeofenceAlert.tracker_id == tracker_id
            )
        ).order_by(GeofenceAlert.created_at.desc()).limit(2).all()
        
        last_alert = last_alerts[0] if last_alerts else None
        
        # Debouncing
        if last_alert:
            time_since_last = datetime.now(timezone.utc) - last_alert.created_at
            if time_since_last.total_seconds() < 60:  # 60 second debounce
                return alerts
        
        # Determine what event type this route POI *would* generate, then apply the
        # global pair guard before creating the actual alert.
        pending_event_type: Optional[GeofenceEventType] = None
        pending_location_name: Optional[str] = None

        # Check for package leaving origin
        if last_alert and last_alert.event_type == GeofenceEventType.ENTRY:
            if not is_at_origin:
                pending_event_type = GeofenceEventType.EXIT
                pending_location_name = "origin"

        # Check for package arriving at destination (no prior alert, or last was EXIT)
        elif not last_alert or last_alert.event_type == GeofenceEventType.EXIT:
            if is_at_destination:
                pending_event_type = GeofenceEventType.ENTRY
                pending_location_name = "destination"
            elif not last_alert and is_at_origin:
                # First ever check and package is sitting at origin: record initial ENTRY
                pending_event_type = GeofenceEventType.ENTRY
                pending_location_name = "origin"

        # Global pairing guard — same rule as single POI: no two consecutive same-type alerts.
        if pending_event_type is not None and last_global_event_type is not None:
            if pending_event_type == last_global_event_type:
                logger.warning(
                    f"GLOBAL PAIR GUARD (route): Suppressing {pending_event_type.value} for "
                    f"'{poi.name}' / tracker {tracker_id} — last global alert was also "
                    f"{last_global_event_type.value}. Alerts must alternate EXIT ↔ ENTRY."
                )
                pending_event_type = None

        if pending_event_type is not None:
            alert = GeofenceAlert(
                poi_id=poi.id,
                tracker_id=tracker_id,
                user_id=user_id,
                event_type=pending_event_type,
                latitude=current_lat,
                longitude=current_lon,
                is_read=False
            )
            db.add(alert)
            alerts.append(alert)
            logger.info(
                f"Route alert: Package {'LEFT' if pending_event_type == GeofenceEventType.EXIT else 'ARRIVED AT'} "
                f"{pending_location_name} for {poi.name}"
            )
            GeofenceService._send_email_alert(
                db, user_id, tracker_id, poi, pending_event_type,
                current_lat, current_lon, location_name=pending_location_name
            )

        return alerts
    
    @staticmethod
    def _send_email_alert(
        db: Session,
        user_id: str,
        tracker_id: str,
        poi: POI,
        event_type: GeofenceEventType,
        latitude: float,
        longitude: float,
        location_name: Optional[str] = None
    ):
        """Send email alert for geofence event"""
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user or not getattr(user, 'email_alerts_enabled', True):
                return
            
            # Get tracker details
            tracker = db.query(BLETag).filter(BLETag.id == tracker_id).first()
            if tracker:
                # Priority: description > device_name > IMEI (last 4 digits) > generic name
                if tracker.description:
                    tracker_name = tracker.description
                elif tracker.device_name:
                    tracker_name = tracker.device_name
                elif tracker.imei:
                    # Use last 4 digits of IMEI for user-friendly identification
                    tracker_name = f"GPS Tracker ({tracker.imei[-4:]})"
                else:
                    tracker_name = "GPS Tracker"
            else:
                tracker_name = "GPS Tracker"
            
            # Customize message format based on POI type and event
            if poi.poi_type == POIType.ROUTE and location_name:
                # Route-specific messages
                if event_type == GeofenceEventType.EXIT and location_name == "origin":
                    event_description = f"left origin ({poi.name})"
                elif event_type == GeofenceEventType.ENTRY and location_name == "destination":
                    event_description = f"arrived at destination ({poi.name})"
                else:
                    event_description = f"at {location_name} ({poi.name})"
            else:
                # Single POI - use "inside" or "outside" messaging
                if event_type == GeofenceEventType.ENTRY:
                    event_description = "Inside"
                else:  # EXIT
                    event_description = "Outside"
            
            # Send email
            email_service = EmailService()
            email_service.send_geofence_alert(
                to_email=user.email,
                event_type=event_description,
                poi_name=poi.name,
                tracker_name=tracker_name,
                latitude=latitude,
                longitude=longitude,
                timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            )
            logger.info(f"Email alert sent to {user.email}")
        except Exception as e:
            logger.error(f"Failed to send email alert: {e}")
    
    @staticmethod
    def get_user_alerts(
        db: Session,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False
    ) -> Tuple[List[GeofenceAlert], int, int]:
        """
        Get alerts for a user
        Returns: (alerts, total_count, unread_count)
        """
        query = db.query(GeofenceAlert).filter(GeofenceAlert.user_id == user_id)
        
        if unread_only:
            query = query.filter(GeofenceAlert.is_read == False)
        
        total_count = query.count()
        unread_count = db.query(GeofenceAlert).filter(
            and_(
                GeofenceAlert.user_id == user_id,
                GeofenceAlert.is_read == False
            )
        ).count()
        
        alerts = query.order_by(
            GeofenceAlert.created_at.desc()
        ).limit(limit).offset(offset).all()
        
        return alerts, total_count, unread_count
    
    @staticmethod
    def mark_alerts_read(db: Session, alert_ids: List[str], user_id: str) -> int:
        """
        Mark alerts as read
        Returns number of alerts updated
        """
        result = db.query(GeofenceAlert).filter(
            and_(
                GeofenceAlert.id.in_(alert_ids),
                GeofenceAlert.user_id == user_id
            )
        ).update({GeofenceAlert.is_read: True}, synchronize_session=False)
        
        db.commit()
        return result
    
    @staticmethod
    def mark_all_alerts_read(db: Session, user_id: str) -> int:
        """
        Mark all alerts for a user as read
        Returns number of alerts updated
        """
        result = db.query(GeofenceAlert).filter(
            and_(
                GeofenceAlert.user_id == user_id,
                GeofenceAlert.is_read == False
            )
        ).update({GeofenceAlert.is_read: True}, synchronize_session=False)
        
        db.commit()
        return result
