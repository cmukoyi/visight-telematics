"""Demo data for one user group: five long-haul trucks and three months of everything the platform shows.

    docker compose exec backend python -m app.scripts.seed_demo --group utrack-logistics
    docker compose exec backend python -m app.scripts.seed_demo --group utrack-logistics --reset   # remove it again

Creates, in that group only: vehicle groups and security groups, a Fleet Manager role and staff users, drivers with
keys, depots / customers / truck stops, five trucks (Volvo, Scania, Mercedes-Benz, MAN, DAF) and their tracker data for
the last --days days — trips along the N1, N2, N3 and N10 with rest and overnight stops, speeding, harsh driving and
idling — built into trips by the platform's own trip builder, then place visits, maintenance (schedules, jobs, costs,
workshops), breakdowns (one under way now, one the tracker disputes), fleet costs, inbox alerts, rules and scheduled
reports. Everything it creates is marked as demo data (vehicles: attributes._demo; places: notes; drivers: UT-
numbers; users: @utracklogistics.co.za), and --reset removes exactly that.

The tracker records never reach the live ingest, so no alert emails are sent; the demo users have email notifications
off.
"""
import argparse
import math
import random
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import insert, or_, text

import app.main  # noqa: F401  (registers every model)
from app.admin_auth import hash_password
from app.database import SessionLocal
from app.models import (POI, BLETag, Driver, FleetSettings, GeofenceStatus, NotificationRule, PlaceGroup, PlaceVisit,
                        PortalAlert, PortalRole, PortalUser, PortalUserRole, POITrackerLink, SecurityGroup, TagCategory,
                        TimeProfile, UserGroup)
from app.models_dataprofiler import DeviceEvent, GeocodeCache, ReportSchedule, Trip, TripBuilderState
from app.models_maintenance import (MaintenanceCost, MaintenanceItem, MaintenanceLookup, MaintenanceSchedule, MaintenanceType,
                                    VehicleBreakdown, VehicleMaintenance, Workshop)
from app.scripts import demo_data as D
from app.services import access_service, address_service, geofence_engine, trip_builder

TZ = ZoneInfo("Africa/Johannesburg")
DEMO_NOTE = "Demo data (seed_demo)"
PASSWORD = "Utrack@Demo2026"
SPEED_LIMIT = 85
STEP = timedelta(minutes=2)
UTC = timezone.utc


def hav(a, b) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(x))


def bearing(a, b) -> int:
    y = math.sin(math.radians(b[1] - a[1])) * math.cos(math.radians(b[0]))
    x = (math.cos(math.radians(a[0])) * math.sin(math.radians(b[0]))
         - math.sin(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.cos(math.radians(b[1] - a[1])))
    return int((math.degrees(math.atan2(y, x)) + 360) % 360)


class Path:
    """A polyline you can walk along by distance."""

    def __init__(self, pts):
        self.pts = pts
        self.cum = [0.0]
        for a, b in zip(pts, pts[1:]):
            self.cum.append(self.cum[-1] + hav(a, b))
        self.length = self.cum[-1]

    def at(self, d):
        d = max(0.0, min(d, self.length))
        i = max(0, min(len(self.cum) - 2, next((k for k in range(1, len(self.cum)) if self.cum[k] >= d), len(self.cum) - 1) - 1))
        seg = self.cum[i + 1] - self.cum[i] or 1
        f = (d - self.cum[i]) / seg
        a, b = self.pts[i], self.pts[i + 1]
        return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f), bearing(a, b)


class Seeder:
    def __init__(self, db, group, days):
        self.db, self.group, self.gid, self.days = db, group, group.id, days
        self.now = datetime.now(UTC).replace(microsecond=0)
        self.start = (self.now - timedelta(days=days)).astimezone(TZ).replace(hour=0, minute=0, second=0).astimezone(UTC)
        self.places = {}        # name → POI
        self.city_places = {}   # city → [(name, lat, lng)] customers and depots
        self.depot = {}         # city → depot name
        self.stops = []         # truck stops (name, lat, lng)
        self.cache_parts = {}   # (lat_e4, lng_e4) → parts
        self.trucks = {}        # key → BLETag
        self.drivers = {}       # employee no. → Driver
        self.users = {}         # "first last" → PortalUser
        self.notable = {}       # key → [(at, code, lat, lng, speed)] alertable events
        self.parked = {}        # key → [(from, to, city, place)] parked spells
        self.odo_track = {}     # key → [(at, odo m)]
        self.breakdowns = []    # dicts for VehicleBreakdown
        self.dp = -9_000_000_000_000

    # ── Setup ──────────────────────────────────────────────────────────
    def setup(self):
        db, g = self.db, self.group
        g.timezone = g.timezone or "Africa/Johannesburg"
        g.location_format = ["landmark_distance", "landmark", "road", "suburb", "town"]
        fs = db.get(FleetSettings, self.gid) or FleetSettings(usergroup_id=self.gid, values={})
        fs.values = {**(fs.values or {}), "fuel_price": 22.85, "default_l_per_100km": 35.0, "idle_l_per_hour": 2.8,
                     "excess_idle_minutes": 10, "speed_limit_kmh": SPEED_LIMIT, "speeding_cost_per_hour": 280.0,
                     "after_hours_cost_per_km": 4.5, "tracking_fee_per_month": 349.0, "licence_fee_per_year": 0.0}
        db.merge(fs)
        access_service.ensure_defaults(db, self.gid)
        self.tp = TimeProfile(usergroup_id=self.gid, name="Long-haul shift", is_default=True,
                              windows={**{str(d): [["04:00", "20:00"]] for d in range(5)}, "5": [["05:00", "14:00"]]})
        db.add(self.tp)
        # Security and vehicle groups
        self.security = {}
        for name in {sg for _, sg in D.VEHICLE_GROUPS.values()}:
            self.security[name] = SecurityGroup(usergroup_id=self.gid, name=name, description=f"{name} vehicles ({DEMO_NOTE})")
            db.add(self.security[name])
        db.flush()
        for name, (color, sg) in D.VEHICLE_GROUPS.items():
            db.add(TagCategory(usergroup_id=self.gid, name=name, color=color, icon="fa-truck", is_active=True,
                               security_group_id=self.security[sg].id))
        # Places
        groups = {}
        for name, color in D.PLACE_GROUPS.items():
            groups[name] = PlaceGroup(usergroup_id=self.gid, name=name, color=color)
            db.add(groups[name])
        db.flush()
        for (name, grp, city, lat, lng, radius, road, suburb, town, postal, prov) in D.PLACES:
            p = POI(usergroup_id=self.gid, name=name, poi_type="single", latitude=lat, longitude=lng, radius=radius,
                    address=f"{road}, {suburb}, {town}, {postal}", shape_type="circle", notes=DEMO_NOTE,
                    place_group_id=groups[grp].id, is_active=True)
            db.add(p)
            self.places[name] = p
            self._cache(lat, lng, {"road": road, "suburb": suburb if suburb != town else None, "town": town,
                                   "postal_code": postal, "province": D.PROVINCE[prov], "country": "South Africa"})
            if grp == "Truck stops":
                self.stops.append((name, lat, lng))
            else:
                self.city_places.setdefault(city, []).append((name, lat, lng))
                if grp == "Depots":
                    self.depot[city] = name
        db.flush()
        # Drivers
        for first, last, emp, key, phone, _truck, _style in D.DRIVERS:
            d = Driver(usergroup_id=self.gid, first_name=first, last_name=last, employee_number=emp, key_code=key, phone=phone)
            db.add(d)
            self.drivers[emp] = d
        db.flush()
        # Roles and users
        roles = {r.name: r for r in db.query(PortalRole).filter(PortalRole.usergroup_id == self.gid)}
        roles["Fleet Manager"] = PortalRole(usergroup_id=self.gid, name="Fleet Manager", is_admin=False, is_system=False,
                                            description="Runs the fleet day to day: tracking, places, maintenance, reports",
                                            permissions=D.FLEET_MANAGER_PERMISSIONS)
        db.add(roles["Fleet Manager"])
        db.flush()
        pw = hash_password(PASSWORD)

        def user(first, last, role_names, sg, mobile=False):
            email = f"{first}.{last}".lower().replace(" ", "") + "@" + D.EMAIL_DOMAIN
            u = PortalUser(usergroup_id=self.gid, email=email, hashed_password=pw, first_name=first, last_name=last,
                           is_active=True, is_group_admin=False, role="custom", notify_via_email=False, alerts_enabled=True,
                           security_group_id=self.security[sg].id if sg else None,
                           last_login_at=self.now - timedelta(hours=random.randint(2, 70)),
                           last_active_at=self.now - timedelta(minutes=random.randint(5, 600)),
                           app_version="0.1.0+57 4e504ae android" if mobile else None)
            db.add(u)
            db.flush()
            for rn in role_names:
                db.add(PortalUserRole(user_id=u.id, role_id=roles[rn].id))
            self.users[f"{first} {last}"] = u
            return u

        for first, last, _title, role_names, sg in D.STAFF:
            user(first, last, role_names, sg)
        for first, last, emp, _key, _phone, truck, _style in D.DRIVERS:
            # Relief drivers cover the KZN trucks
            region = D.VEHICLE_GROUPS[D.TRUCKS[[t[0] for t in D.TRUCKS].index(truck)][6]][1] if truck else "KZN Operations"
            user(first, last, ["MZone Driver"], region, mobile=True)
        # Maintenance setup
        self.vtype = MaintenanceLookup(usergroup_id=self.gid, kind="vehicle_type", name="Truck tractor 6x4")
        db.add(self.vtype)
        self.cost_centres = {n: MaintenanceLookup(usergroup_id=self.gid, kind="cost_centre", name=n)
                             for n in ("Long-haul operations", "Coastal operations", "Workshop overheads")}
        chains = {n: MaintenanceLookup(usergroup_id=self.gid, kind="workshop_chain", name=n)
                  for n in ("Volvo Trucks SA", "Scania South Africa", "Mercedes-Benz Trucks", "MAN Truck & Bus", "DAF Trucks SA",
                            "Supa Quick")}
        wtypes = {n: MaintenanceLookup(usergroup_id=self.gid, kind="workshop_type", name=n)
                  for n in ("OEM dealer", "Tyres", "Brakes and clutch")}
        for x in [*self.cost_centres.values(), *chains.values(), *wtypes.values()]:
            db.add(x)
        db.flush()
        self.workshops = {}
        for key, name, chain, wt, phone in [
            ("volvo", "Volvo Trucks Durban (Bayhead)", "Volvo Trucks SA", "OEM dealer", "+27 31 205 1180"),
            ("scania", "Scania Isando", "Scania South Africa", "OEM dealer", "+27 11 923 7100"),
            ("actros", "Mercedes-Benz Trucks Montague Gardens", "Mercedes-Benz Trucks", "OEM dealer", "+27 21 555 4000"),
            ("man", "MAN Truck & Bus Pinetown", "MAN Truck & Bus", "OEM dealer", "+27 31 700 9320"),
            ("daf", "DAF Trucks Germiston", "DAF Trucks SA", "OEM dealer", "+27 11 827 2601"),
            ("tyres", "Supa Quick Commercial Jacobs", "Supa Quick", "Tyres", "+27 31 461 2238"),
        ]:
            w = Workshop(usergroup_id=self.gid, name=name, chain_id=chains[chain].id, phone=phone, type_ids=[str(wtypes[wt].id)],
                         working_hours="Mon–Fri 07:00–17:00, Sat 07:30–12:30")
            db.add(w)
            self.workshops[key] = w
        items = {}
        for n in ("Engine oil (40 L)", "Oil filter", "Fuel filters", "Air filter", "Gearbox oil", "Differential oil",
                  "Brake linings (all axles)", "Brake drums", "Drive tyres (set of 8)", "Steer tyres (pair)", "Wheel alignment",
                  "Grease fifth wheel and chassis", "Labour", "Certificate of fitness (COF) test"):
            items[n] = MaintenanceItem(usergroup_id=self.gid, name=n, is_system=False)
            db.add(items[n])
        db.flush()
        self.items = items
        self.types = {}
        for key, name, hours, its in [
            ("A", "A-service (oil and filters)", 8, ["Engine oil (40 L)", "Oil filter", "Fuel filters", "Air filter", "Grease fifth wheel and chassis", "Labour"]),
            ("B", "B-service (major)", 24, ["Engine oil (40 L)", "Oil filter", "Fuel filters", "Air filter", "Gearbox oil", "Differential oil", "Labour"]),
            ("brakes", "Brake overhaul", 12, ["Brake linings (all axles)", "Brake drums", "Labour"]),
            ("tyres", "Tyre replacement", 4, ["Drive tyres (set of 8)", "Wheel alignment", "Labour"]),
            ("cof", "Annual COF roadworthy", 6, ["Certificate of fitness (COF) test", "Labour"]),
        ]:
            self.types[key] = MaintenanceType(usergroup_id=self.gid, name=name, duration_hours=hours, item_ids=[str(items[i].id) for i in its])
            db.add(self.types[key])
        db.flush()
        start_day = (self.now - timedelta(days=720)).date()
        self.schedules = {
            "A": MaintenanceSchedule(usergroup_id=self.gid, type_id=self.types["A"].id, name="A-service every 40 000 km", starts_on=start_day,
                                     at_km=40000, recurring=True, every_km=40000, remind_km=1500, remind_days=14,
                                     vehicle_type_ids=[str(self.vtype.id)], imeis=[]),
            "B": MaintenanceSchedule(usergroup_id=self.gid, type_id=self.types["B"].id, name="B-service every 120 000 km", starts_on=start_day,
                                     at_km=120000, recurring=True, every_km=120000, remind_km=3000, remind_days=14,
                                     vehicle_type_ids=[str(self.vtype.id)], imeis=[]),
            "cof": MaintenanceSchedule(usergroup_id=self.gid, type_id=self.types["cof"].id, name="Annual COF roadworthy", starts_on=start_day,
                                       at_months=12, recurring=True, every_months=12, remind_days=21,
                                       vehicle_type_ids=[str(self.vtype.id)], imeis=[]),
        }
        for s in self.schedules.values():
            db.add(s)
        db.flush()
        # Trucks
        for (key, desc, make, model, year, reg, vgroup, lper100, odo_km, lic_days) in D.TRUCKS:
            lic = (self.now - timedelta(days=lic_days)).astimezone(TZ).date().isoformat()
            emp = next(e for (_, _, e, _, _, t, _) in D.DRIVERS if t == key)
            d = self.drivers[emp]
            imei = "35999" + str(abs(hash((self.gid, key))) % 10**10).zfill(10)
            while db.query(BLETag.id).filter(BLETag.imei == imei).first():
                imei = str(int(imei) + 1)
            attrs = {"_created_usergroup_id": str(self.gid), "_demo": True, "category": {"value": vgroup},
                     "registration": {"value": reg}, "make": {"value": make}, "model": {"value": model}, "year": {"value": year},
                     "driver": {"value": f"{d.first_name} {d.last_name}"}, "driver_id": {"value": str(d.id)},
                     "fuel_consumption": {"value": lper100}, "vehicle_type": {"value": str(self.vtype.id)},
                     "licence_start": {"value": lic}, "time_profile_id": {"value": str(self.tp.id)}}
            t = BLETag(imei=imei, tag_type="teltonika", description=desc, device_name=f"FMC650-{imei[-5:]}",
                       device_model="Teltonika FMC650", is_active=True, attributes=attrs, battery_level=100,
                       activation_date=self.start - timedelta(days=400))
            db.add(t)
            self.trucks[key] = t
        db.flush()
        db.commit()

    def _cache(self, lat, lng, parts):
        self.cache_parts[(round(lat * 10000), round(lng * 10000))] = parts

    # ── Tracker data ───────────────────────────────────────────────────
    def simulate(self):
        for (key, *_rest) in D.TRUCKS:
            Truck(self, key).run()

    # ── After the trips: places, maintenance, breakdowns, alerts ───────
    def finish(self):
        db = self.db
        # Breakdown spots (and where the towed truck ended up) have addresses too
        for b in self.breakdowns:
            parts = {"road": b["road"], "town": b["town"], "province": b["province"], "country": "South Africa"}
            self._cache(*b["pos"], parts)
            self._cache(*b["phone"], parts)
            if b.get("end_pos"):
                self._cache(*b["end_pos"], parts)
        # Cached addresses for every place and stop, then trip start / end addresses from them
        rows = [{"lat_e4": a, "lng_e4": b, "address": address_service.default_text(p), "parts": p}
                for (a, b), p in self.cache_parts.items()]
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        for i in range(0, len(rows), 500):
            db.execute(pg_insert(GeocodeCache.__table__).values(rows[i:i + 500]).on_conflict_do_nothing())
        for t in db.query(Trip).filter(Trip.imei.in_([x.imei for x in self.trucks.values()])):
            for side in ("start", "end"):
                lat, lng = getattr(t, f"{side}_latitude"), getattr(t, f"{side}_longitude")
                if lat is not None and getattr(t, f"{side}_address") is None:
                    p = self.cache_parts.get((round(lat * 10000), round(lng * 10000)))
                    if p:
                        setattr(t, f"{side}_address", address_service.default_text(p))
        db.commit()
        print("  place visits:", geofence_engine.rebuild_visits(db, self.gid))
        db.commit()
        Maintenance(self).run()
        self._breakdowns()
        self._alerts()
        self._extras()
        db.commit()

    def _breakdowns(self):
        db = self.db
        from app.services import breakdown_service
        btype = breakdown_service.breakdown_type(db, self.gid)
        for b in self.breakdowns:
            tag = self.trucks[b["key"]]
            ended = b.get("end")
            job = VehicleMaintenance(usergroup_id=self.gid, imei=tag.imei, description=f"Breakdown: {b['cause']}", type_id=btype.id,
                                     planned_start=b["start"], planned_end=b["start"] + timedelta(hours=4), actual_start=b["start"],
                                     actual_end=ended, odometer_km=int(b["odo"] / 1000), reference="Mobile app",
                                     notes=f"Logged by {b['by']} in the mobile app." + (f"\n{b['notes']}" if b.get("notes") else ""),
                                     created_by=self.users[b["by"]].email)
            db.add(job)
            db.flush()
            bd = VehicleBreakdown(usergroup_id=self.gid, imei=tag.imei, job_id=job.id, reported_by_id=self.users[b["by"]].id,
                                  reported_by=b["by"], driver=b["by"], cause=b["cause"], started_at=b["start"], ended_at=ended,
                                  start_lat=b["phone"][0], start_lng=b["phone"][1], start_accuracy=b.get("accuracy", 8.0),
                                  end_lat=b["end_pos"][0] if ended else None, end_lng=b["end_pos"][1] if ended else None,
                                  phases=[{"phase": ph, "at": at.isoformat(), "lat": b["pos"][0], "lng": b["pos"][1]} for ph, at in b["phases"]],
                                  notes=b.get("notes"), review=b.get("review"), review_note=b.get("review_note"),
                                  reviewed_by="Thandi Mokoena" if b.get("review") else None)
            db.add(bd)
            db.flush()
            self._alert(tag, "breakdown", f"{tag.description} broke down",
                        f"{b['by']} logged a breakdown ({b['cause'].lower()}) for {tag.description}.", b["start"] + timedelta(seconds=20),
                        {"latitude": b["phone"][0], "longitude": b["phone"][1], "breakdown_id": str(bd.id)})


    def _alert(self, tag, atype, title, message, at, meta, read=None):
        old = at < self.now - timedelta(days=2)
        read = old if read is None else read
        a = PortalAlert(usergroup_id=self.gid, tag_id=tag.id, alert_type=atype, title=title[:200], message=message, is_read=read,
                        created_at=at, meta_data=meta, read_at=at + timedelta(minutes=random.randint(20, 300)) if read else None,
                        read_by="Thandi Mokoena" if read else None)
        if read and random.random() < 0.25:
            a.notes = random.choice(["Checked with the driver.", "Expected — scheduled delivery.", "Spoke to the driver about speed.",
                                     "Customer confirmed arrival.", "Logged for the monthly driver review."])
        self.db.add(a)

    def _alerts(self):
        db = self.db
        since = self.now - timedelta(days=7)
        by_imei = {t.imei: (k, t) for k, t in self.trucks.items()}
        armed = {p.id for n, p in self.places.items() if n in self.depot.values()}
        for v in db.query(PlaceVisit).filter(PlaceVisit.usergroup_id == self.gid, PlaceVisit.poi_id.in_(armed)):
            key, tag = by_imei[v.imei]
            poi = db.get(POI, v.poi_id)
            reg = tag.attributes["registration"]["value"]
            for when, entered, speed in ((v.entered_at, True, v.entry_speed), (v.exited_at, False, v.exit_speed)):
                if when is None or when < since:
                    continue
                verb = "entered" if entered else "left"
                self._alert(tag, "geofence_entry" if entered else "geofence_exit", f"{tag.description} {verb} {poi.name}",
                            f"{tag.description} {verb} the place '{poi.name}' at {when.astimezone(TZ):%d %b %Y %H:%M} ({speed or 0} km/h).", when,
                            {"poi_name": poi.name, "poi_id": str(poi.id), "imei": tag.imei, "event_type": "entry" if entered else "exit",
                             "latitude": poi.latitude, "longitude": poi.longitude, "speed": speed or 0, "recorded_at": when.isoformat(),
                             "rules": ["Depot arrivals and departures"], "registration": reg})
        labels = {"overspeed": "Speeding", "harsh_braking": "Harsh braking", "harsh_acceleration": "Harsh acceleration",
                  "harsh_cornering": "Harsh cornering"}
        for key, events in self.notable.items():
            tag = self.trucks[key]
            for at, code, lat, lng, speed in events:
                if at < since:
                    continue
                self._alert(tag, f"event_{code}", f"{tag.description}: {labels[code]}",
                            f"{tag.description} reported {labels[code]} at {at.astimezone(TZ):%d %b %Y %H:%M} ({speed} km/h).", at,
                            {"imei": tag.imei, "event_code": code, "event_label": labels[code], "latitude": lat, "longitude": lng,
                             "speed": speed, "recorded_at": at.isoformat(), "rules": ["Speeding and harsh driving"],
                             "registration": tag.attributes["registration"]["value"]})
        # Licences: the MAN's expired last week
        man = self.trucks["man"]
        from app.services.licence_service import expiry
        ends = expiry(date.fromisoformat(man.attributes["licence_start"]["value"]))
        at = datetime.combine(ends, time(7, 0), tzinfo=TZ).astimezone(UTC)
        if at < self.now:
            self._alert(man, "licence_expired", f"{man.description}: licence expired",
                        f"The vehicle licence for {man.description} ({man.attributes['registration']['value']}) expired on {ends:%d %b %Y}.",
                        at, {"imei": man.imei, "registration": man.attributes["registration"]["value"],
                             "licence_start": man.attributes["licence_start"]["value"], "licence_expires": ends.isoformat(), "days_left": -1})

    def _extras(self):
        db = self.db
        fm = self.users["Thandi Mokoena"]
        depots = db.query(PlaceGroup).filter(PlaceGroup.usergroup_id == self.gid, PlaceGroup.name == "Depots").all()
        db.add(NotificationRule(usergroup_id=self.gid, name="Depot arrivals and departures", rule_type="geofence",
                                place_group_ids=[str(p.id) for p in depots], on_entry=True, on_exit=True, email_enabled=False,
                                is_active=True, created_by=fm.id))
        db.add(NotificationRule(usergroup_id=self.gid, name="Speeding and harsh driving", rule_type="event",
                                event_codes=["overspeed", "harsh_braking", "harsh_acceleration", "harsh_cornering"],
                                email_enabled=False, is_active=True, created_by=fm.id))
        nxt = (self.now + timedelta(days=(7 - self.now.weekday()) % 7 or 7)).replace(hour=4, minute=0, second=0)
        for key, name, freq, recips in [
            ("trips", "Weekly trip detail", "weekly", [fm.email]),
            ("speeding_summary", "Weekly speeding summary", "weekly", [fm.email]),
            ("breakdowns", "Monthly breakdowns", "monthly", [fm.email, self.users["Pieter van der Merwe"].email]),
        ]:
            db.add(ReportSchedule(usergroup_id=self.gid, created_by=fm.id, report_key=key, name=name, frequency=freq, file_format="xlsx",
                                  recipients=recips, params={}, timezone="Africa/Johannesburg", send_hour=6, is_active=True, next_run_at=nxt))


class Truck:
    """One truck's three months: lanes city to city, rest and overnight stops, speeding, harsh driving, idling, breakdowns."""

    def __init__(self, s: Seeder, key):
        self.s, self.key = s, key
        row = next(t for t in D.TRUCKS if t[0] == key)
        self.tag = s.trucks[key]
        self.odo = row[8] * 1000
        main = next(d for d in D.DRIVERS if d[5] == key)
        self.main_driver = main
        self.relief = [d for d in D.DRIVERS if d[5] is None]
        self.events = []
        self.t = s.start + timedelta(hours=random.uniform(2, 20))
        self.city = D.HOME[key]
        self.place = s.depot.get(self.city) or s.city_places[self.city][0][0]
        self.pos = self._place_pos(self.place)
        self.lane = D.LANES[key]
        self.lane_i = 0
        s.notable[key], s.parked[key], s.odo_track[key] = [], [], []
        self.driving_today = timedelta(0)
        self.breakdown_plan = BREAKDOWNS.get(key, [])
        self.active_bd = key == ACTIVE_BREAKDOWN
        self.ign = False
        self.stopped = False

    def _place_pos(self, name):
        p = self.s.places[name]
        return (p.latitude, p.longitude)

    # Event records
    def emit(self, io_id, io, speed=0, angle=0, pos=None):
        if self.t > self.s.now or self.stopped:
            return
        self.s.dp -= 1
        lat, lng = pos or self.pos
        base = {"16": int(self.odo), "66": random.randint(27400, 28200) if self.ign else random.randint(25100, 25600),
                "21": random.randint(3, 5), "69": 1, "239": 1 if self.ign else 0, "240": 1 if speed > 0 else 0, "24": speed}
        self.events.append({"dp_event_id": self.s.dp, "imei": self.tag.imei, "usergroup_id": self.s.gid, "recorded_at": self.t,
                            "received_at": self.t + timedelta(seconds=random.randint(2, 40)), "event_io_id": io_id,
                            "priority": 0 if io_id == 0 else 1, "latitude": round(lat, 6),
                            "longitude": round(lng, 6), "altitude": D.INLAND(lat, lng) + random.randint(-40, 40),
                            "angle": angle, "satellites": random.randint(11, 17), "speed": speed, "io": {**base, **io}})

    def park_until(self, until, city=None, place=None):
        """Ignition off: a parked record now and every 4 h until `until`."""
        start = self.t
        step = timedelta(minutes=30)
        while self.t + step < until:
            self.t += step + timedelta(seconds=random.randint(-60, 60))
            self.emit(0, {})
            step = timedelta(hours=1)
        self.t = until
        self.s.parked[self.key].append((start, until, city, place))

    def trip_start(self, driver):
        self.ign = True
        self.emit(250, {"250": 1, "78": int(driver[3], 16)})

    def trip_end(self, idle_min=0):
        if idle_min:
            self.emit(251, {"251": 1})
            self.t += timedelta(minutes=idle_min)
            self.emit(251, {"251": 0})
        self.ign = False
        self.emit(250, {"250": 0})

    # The lanes
    def run(self):
        s = self.s
        while self.t < s.now and not self.stopped:
            nxt_city = self.lane[(self.lane_i + 1) % len(self.lane)]
            if nxt_city == self.city:
                self.lane_i += 1
                continue
            # Depart: next morning 04:00–06:00 local (sometimes a rest day; Sundays mostly off at home)
            local = self.t.astimezone(TZ)
            depart = (local + timedelta(days=1 if local.hour >= 3 else 0)).replace(hour=4, minute=0, second=0) + timedelta(minutes=random.randint(0, 110))
            while depart.weekday() == 6 and self.city == D.HOME[self.key] and random.random() < 0.85:
                depart += timedelta(days=1)
            if random.random() < 0.2:
                depart += timedelta(days=1)   # loading, a rest day
            depart = depart.astimezone(UTC)
            if self.active_bd and self.t < s.now - timedelta(hours=3) < depart:
                depart = s.now - timedelta(hours=3, minutes=10)   # be on the road when the live breakdown happens
            self.park_until(max(depart, self.t + timedelta(hours=8)), self.city, self.place)
            if self.t >= s.now:
                break
            dest_city = nxt_city
            dest = s.depot.get(dest_city) if dest_city == D.HOME[self.key] or random.random() < 0.3 else None
            dest = dest or random.choice([p for p in s.city_places[dest_city] if not p[0].startswith("Utrack")] or s.city_places[dest_city])[0]
            road = D.ROADS.get((self.city, dest_city)) or list(reversed(D.ROADS[(dest_city, self.city)]))
            self.road_name = D.ROAD_NAMES.get((self.city, dest_city)) or D.ROAD_NAMES[(dest_city, self.city)]
            path = Path([self.pos, *road, self._place_pos(dest)])
            driver = random.choice(self.relief) if random.random() < 0.12 else self.main_driver
            self.drive(path, driver, dest_city)
            if self.stopped:
                break
            self.city, self.place, self.pos = dest_city, dest, self._place_pos(dest)
            self.lane_i += 1
            # Offload and back to the depot when it's the home city
            if dest_city == D.HOME[self.key] and dest != s.depot.get(dest_city) and self.t < s.now:
                self.park_until(self.t + timedelta(hours=random.uniform(1.5, 3.5)), dest_city, dest)
                home = s.depot[dest_city]
                self.drive(Path([self.pos, self._place_pos(home)]), driver, dest_city, local=True)
                self.place, self.pos = home, self._place_pos(home)
        self.flush()

    def drive(self, path, driver, dest_city, local=False):
        s = self.s
        style = driver[6]
        p_burst = {"careful": 0.0008, "normal": 0.003, "heavy-footed": 0.009}[style]
        p_harsh = {"careful": 0.0004, "normal": 0.0011, "heavy-footed": 0.003}[style]   # per km
        cruise = random.uniform(77, 82)
        d, burst, since_stop = 0.0, 0, timedelta(0)
        self.driving_today = timedelta(0)
        self.trip_start(driver)
        stops_used = set()
        while d < path.length and self.t < s.now and not self.stopped:
            pos, ang = path.at(d)
            left = path.length - d
            # Speed: towns at either end, climbs, cruise, and the odd burst over the limit
            if d < 9000 or left < 9000 or local:
                speed = random.randint(28, 58)
            elif any(hav(pos, (a, b)) < r * 1000 for a, b, r in D.SLOW):
                speed = random.randint(38, 62)
            else:
                speed = int(cruise + random.gauss(0, 3.2))
                if burst == 0 and random.random() < p_burst:
                    burst = random.randint(2, 5)
                    speed = random.randint(SPEED_LIMIT + 3, SPEED_LIMIT + 19)
                    self.emit(255, {"255": speed}, speed, ang, pos)
                    s.notable[self.key].append((self.t, "overspeed", pos[0], pos[1], speed))
                elif burst:
                    burst -= 1
                    speed = random.randint(SPEED_LIMIT + 1, SPEED_LIMIT + 16) if burst else speed
            self.pos = pos
            self.emit(0, {}, speed, ang, pos)
            step_m = speed * STEP.total_seconds() / 3.6
            # Harsh driving
            if random.random() < p_harsh * step_m / 1000:
                kind = random.choices([2, 1, 3], [0.5, 0.3, 0.2])[0]
                code = {1: "harsh_acceleration", 2: "harsh_braking", 3: "harsh_cornering"}[kind]
                self.emit(253, {"253": kind, "254": random.randint(28, 62)}, speed, ang, pos)
                s.notable[self.key].append((self.t, code, pos[0], pos[1], speed))
            # Breakdown?
            bd = next((b for b in self.breakdown_plan if not b.get("done") and self.t >= s.start + timedelta(days=s.days - b["days_ago"])
                       and d > 40000 and left > 40000), None)
            if self.active_bd and self.t >= s.now - timedelta(minutes=55) and d > 20000 and left > 20000:
                bd = {"cause": "Battery", "kind": "active", "hours": 99}
            if bd:
                bd["done"] = True
                path, d = self.breakdown(bd, path, d, driver)
                since_stop = timedelta(0)
                continue
            d += step_m
            self.odo += step_m
            self.t += STEP
            since_stop += STEP
            self.driving_today += STEP
            # Rest and overnight stops at truck stops
            near = next((st for st in s.stops if st[0] not in stops_used and hav(pos, (st[1], st[2])) < 2500), None)
            if near and (since_stop > timedelta(hours=2, minutes=20) or self.driving_today > timedelta(hours=7)) and left > 60000:
                stops_used.add(near[0])
                self.pos = (near[1], near[2])
                self.emit(0, {}, random.randint(8, 20), ang)
                self.t += timedelta(minutes=2)
                self.trip_end(idle_min=random.choice([0, 0, 4, 7, 12, 18]))
                overnight = self.driving_today > timedelta(hours=7) and left > 250000
                if overnight:
                    nxt = ((self.t.astimezone(TZ) + timedelta(days=1)).replace(hour=4, minute=0) + timedelta(minutes=random.randint(15, 75))).astimezone(UTC)
                    self.park_until(nxt, None, near[0])
                    self.driving_today = timedelta(0)
                else:
                    self.park_until(self.t + timedelta(minutes=random.randint(22, 48)), None, near[0])
                if self.t >= s.now:
                    return
                self.trip_start(driver)
                since_stop = timedelta(0)
        if self.t < s.now and not self.stopped:
            self.pos = path.pts[-1]
            self.emit(0, {}, random.randint(5, 15), 0)
            self.t += timedelta(minutes=3)
            self.trip_end(idle_min=random.choice([0, 3, 6, 9, 14]))
            s.odo_track[self.key].append((self.t, self.odo))

    def breakdown(self, b, path, d, driver):
        """Stop on the road and log a breakdown; the tracker shows what really happened."""
        s = self.s
        spot = self.pos
        self.t += timedelta(minutes=1)
        self.emit(0, {}, 0, 0)
        self.trip_end()
        start = self.t + timedelta(minutes=random.randint(2, 6))
        by = f"{driver[0]} {driver[1]}"
        near = min(D.PLACES, key=lambda pl: hav(spot, (pl[3], pl[4])))   # the nearest town on the list
        town, province = near[8], D.PROVINCE[near[10]]
        b = {**b, **{k: b[k].format(town=town) for k in ("notes", "review_note") if k in b}}
        rec = {"key": self.key, "cause": b["cause"], "start": start, "pos": spot, "odo": self.odo, "by": by,
               "phone": (spot[0] + random.gauss(0, 0.00012), spot[1] + random.gauss(0, 0.00012)), "road": self.road_name,
               "town": town, "province": province, "phases": []}
        self.t = start
        if b["kind"] == "active":
            rec["phases"] = [("Waiting for dispatch", start + timedelta(minutes=6)), ("Mechanic en route", start + timedelta(minutes=31))]
            rec["phases"] = [p for p in rec["phases"] if p[1] < s.now]
            self.park_until(s.now)
            self.stopped = True
            s.breakdowns.append(rec)
            return path, d
        total = timedelta(hours=b["hours"])
        end = start + total
        rec["phases"] = [("Waiting for dispatch", start + timedelta(minutes=5)),
                         ("Mechanic en route", start + timedelta(minutes=random.randint(25, 60)))]
        if b["kind"] == "towed":
            tow_at = start + total * 0.35
            rec["phases"].append(("Being towed", tow_at))
            self.park_until(tow_at)
            # Towed 30 km on, ignition off
            target = d + 30000
            while d < target and self.t < s.now:
                d += 55 / 3.6 * 120
                self.pos, ang = path.at(d)
                self.odo += 55 / 3.6 * 120
                self.t += STEP
                self.emit(0, {}, 55, ang)
            rec["phases"].append(("Under repair", self.t + timedelta(minutes=20)))
            rec["phases"].append(("Waiting for parts", self.t + timedelta(hours=1, minutes=10)))
        elif b["kind"] == "suspicious":
            # The driver "broke down" but drove 19 km into town and back
            self.park_until(start + timedelta(minutes=35))
            self.trip_start(driver)
            town = (spot[0] + 0.12, spot[1] + 0.09)
            for frac in [i / 9 for i in range(1, 10)] + [1 - i / 9 for i in range(1, 10)]:
                p = (spot[0] + (town[0] - spot[0]) * frac, spot[1] + (town[1] - spot[1]) * frac)
                self.odo += hav(self.pos, p)
                self.pos = p
                self.t += STEP
                self.emit(0, {}, random.randint(45, 72), 30)
                if frac == 1.0:
                    self.trip_end()
                    self.park_until(self.t + timedelta(hours=2, minutes=40))
                    self.trip_start(driver)
            self.trip_end()
            self.pos = spot
            rec["phases"].append(("Under repair", start + total * 0.75))
        else:
            rec["phases"].append(("Under repair", start + total * 0.55))
        self.park_until(max(end, self.t))
        rec["end"], rec["end_pos"] = self.t, self.pos
        rec.update({k: b[k] for k in ("notes", "review", "review_note") if k in b})
        s.breakdowns.append(rec)
        self.t += timedelta(minutes=1)   # driving again after the breakdown is resolved
        self.trip_start(driver)
        return path, d

    def flush(self):
        """Store the records and build trips from them with the platform's trip builder (one transaction)."""
        db = self.s.db
        db.add(TripBuilderState(imei=self.tag.imei, last_event_id=0))
        db.flush()
        for i in range(0, len(self.events), 4000):
            db.execute(insert(DeviceEvent.__table__), self.events[i:i + 4000])
        while trip_builder.process_device(db, self.tag.imei) >= trip_builder.BATCH:
            pass
        last = self.events[-1] if self.events else None
        if last:
            self.tag.latitude, self.tag.longitude = str(last["latitude"]), str(last["longitude"])
            self.tag.last_seen = last["recorded_at"]
        db.commit()
        trips = db.query(Trip).filter(Trip.imei == self.tag.imei).count()
        print(f"  {self.tag.description}: {len(self.events):,} tracker records, {trips} trips, "
              f"{(self.odo / 1000 - next(t[8] for t in D.TRUCKS if t[0] == self.key)):,.0f} km")


# Breakdowns per truck: days ago (roughly), cause, kind, hours, where, and the manager's review
BREAKDOWNS = {
    "man": [{"days_ago": 71, "cause": "Overheating", "kind": "normal", "hours": 6.3, "review": "accepted",
             "notes": "Radiator hose split near {town}. Replaced on site by the MAN road service.",
             "review_note": "Confirmed with the MAN road service invoice."}],
    "scania": [{"days_ago": 48, "cause": "Flat tyre", "kind": "normal", "hours": 2.2, "review": "accepted",
                "notes": "Steer tyre blowout outside {town}. Spare fitted by the Bandag call-out."}],
    "actros": [{"days_ago": 33, "cause": "Electrical", "kind": "towed", "hours": 9.0, "review": "accepted",
                "notes": "Alternator failed. Towed towards {town}; the part came from the Mercedes-Benz dealer."}],
    "volvo": [{"days_ago": 19, "cause": "Engine", "kind": "suspicious", "hours": 4.5, "review": "disputed",
               "notes": "Engine warning light, waited for the mechanic.",
               "review_note": "Tracker shows two trips into {town} with the ignition on during the 'breakdown'. Discussed with the driver."}],
    "daf": [{"days_ago": 5, "cause": "Fuel", "kind": "normal", "hours": 1.4,
             "notes": "Fuel filter blocked near {town}. Cleared and bled the system."}],
}
ACTIVE_BREAKDOWN = "daf"   # broken down right now (Inbox, Breakdowns page "in progress", Maintenance Overview)


class Maintenance:
    """Jobs and costs that fit the trucks' odometers and rest days: A / B services, brakes, tyres, COF, fixed costs."""

    def __init__(self, s: Seeder):
        self.s = s

    def odo_at(self, key, at):
        track = self.s.odo_track[key]
        before = [o for t, o in track if t <= at]
        return int((before[-1] if before else next(t[8] for t in D.TRUCKS if t[0] == key) * 1000) / 1000)

    def gap(self, key, near, min_hours=7):
        """A parked spell at the home city around `near` (the job happens then)."""
        home = D.HOME[key]
        spells = [(a, b) for a, b, city, _ in self.s.parked[key] if city == home and (b - a) >= timedelta(hours=min_hours) and b < self.s.now]
        return min(spells, key=lambda ab: abs((ab[0] - near).total_seconds())) if spells else None

    def job(self, key, typ, sched, start, hours, workshop, ref, costs, odo=None, end=True, notes=None):
        s = self.s
        tag = s.trucks[key]
        t = s.types[typ]
        j = VehicleMaintenance(usergroup_id=s.gid, imei=tag.imei, description=t.name, type_id=t.id,
                               schedule_id=s.schedules[sched].id if sched else None, planned_start=start,
                               planned_end=start + timedelta(hours=t.duration_hours),
                               actual_start=start if end is not None else None,
                               actual_end=start + timedelta(hours=hours) if end else None,
                               odometer_km=odo if odo is not None else self.odo_at(key, start), workshop_id=workshop.id,
                               reference=ref, notes=notes, created_by=s.users["Pieter van der Merwe"].email)
        s.db.add(j)
        s.db.flush()
        cc = s.cost_centres["Coastal operations" if key in ("actros", "man") else "Long-haul operations"]
        for item, amount in costs:
            s.db.add(MaintenanceCost(usergroup_id=s.gid, imei=tag.imei, cost_date=(start + timedelta(hours=hours)).astimezone(TZ).date(),
                                     maintenance_id=j.id, item_id=s.items[item].id, cost_centre_id=cc.id, category="maintenance",
                                     description=item, amount=Decimal(str(round(amount, 2)))))
        return j

    def run(self):
        s = self.s
        a_costs = lambda: [("Engine oil (40 L)", random.uniform(3900, 4400)), ("Oil filter", 690), ("Fuel filters", 1240),
                           ("Air filter", 1580), ("Grease fifth wheel and chassis", 380), ("Labour", random.choice([2850, 3420, 3990]))]
        b_costs = lambda: a_costs() + [("Gearbox oil", 3150), ("Differential oil", 2680), ("Labour", 5400)]
        target_left = {"volvo": 700, "scania": 21000, "actros": 14500, "man": 27000, "daf": 9500}   # km to the next A-service
        n = 0
        for key, tag in s.trucks.items():
            final = self.odo_at(key, s.now)
            first = next(t[8] for t in D.TRUCKS if t[0] == key)
            # The latest A-service, placed so the next one is target_left km away; the one before it 40 000 km earlier
            want = final + target_left[key] - 40000
            km_per_day = max(1.0, (final - first) / s.days)
            for odo in (want, want - 40000):
                at = s.start + timedelta(days=(odo - first) / km_per_day)
                g = self.gap(key, at) if at > s.start + timedelta(days=2) else None
                start = (g[0] + timedelta(hours=2)) if g else at.replace(hour=7)
                self.job(key, "A", "A", start, random.uniform(5.5, 7.5), s.workshops[key], f"WO-{24800 + n}", a_costs(),
                         odo=self.odo_at(key, start) if g else odo)
                n += 1
            # B-service: last one well before, so the next is a while off (Scania's came up this quarter)
            b_odo = final - (random.randint(52000, 95000) if key != "scania" else 21000)
            at = s.start + timedelta(days=(b_odo - first) / km_per_day)
            g = self.gap(key, at, 10) if at > s.start + timedelta(days=2) else None
            start = (g[0] + timedelta(hours=1)) if g else at.replace(hour=7)
            self.job(key, "B", "B", start, random.uniform(14, 22), s.workshops[key], f"WO-{24800 + n}", b_costs(),
                     odo=self.odo_at(key, start) if g else b_odo)
            n += 1
            # COF: a year ago, so it's due this month (the DAF's is three days overdue)
            cof_days = {"volvo": 330, "scania": 300, "actros": 352, "man": 290, "daf": 368}[key]
            start = (s.now - timedelta(days=cof_days)).replace(hour=8)
            self.job(key, "cof", "cof", start, 4, s.workshops[key], f"COF-{key.upper()}-25", [("Certificate of fitness (COF) test", 1250), ("Labour", 950)],
                     odo=first - int(km_per_day * (cof_days - s.days)))
        # One-off work this quarter
        for key, typ, days, costs, ws in [
            ("volvo", "brakes", 40, [("Brake linings (all axles)", 14800), ("Brake drums", 9600), ("Labour", 4200)], "volvo"),
            ("man", "tyres", 55, [("Drive tyres (set of 8)", 46400), ("Wheel alignment", 1150), ("Labour", 900)], "tyres"),
            ("scania", "tyres", 22, [("Drive tyres (set of 8)", 44800), ("Wheel alignment", 1150), ("Labour", 900)], "tyres"),
        ]:
            g = self.gap(key, s.now - timedelta(days=days), 5)
            if g:
                self.job(key, typ, None, g[0] + timedelta(hours=1, minutes=30), s.types[typ].duration_hours - 1, s.workshops[ws],
                         f"WO-{24900 + days}", costs)
        # In the workshop now: the truck parked longest at home (not the broken-down DAF); and one booked next week
        parked_now = [(k, sp) for k in s.trucks if k != ACTIVE_BREAKDOWN for sp in s.parked[k][-1:]
                      if sp[2] == D.HOME[k] and sp[1] >= s.now - timedelta(minutes=5) and s.now - sp[0] > timedelta(hours=3)]
        if parked_now:
            k, sp = max(parked_now, key=lambda x: s.now - x[1][0])
            self.job(k, "brakes", None, max(sp[0] + timedelta(hours=1), s.now - timedelta(hours=5)), 0, s.workshops[k], "WO-25031",
                     [("Brake linings (all axles)", 13900), ("Labour", 3600)], end=False, notes="Brake judder reported by the driver.")
        self.job("scania", "tyres", None, (s.now + timedelta(days=5)).replace(hour=7, minute=30), 0, s.workshops["tyres"], "WO-25040",
                 [], end=None, notes="Steer tyres at 4 mm — booked with Supa Quick.")
        # Fixed and running costs: insurance (monthly, spread), licences (yearly, spread), tolls, fines
        months = sorted({(s.start + timedelta(days=d)).astimezone(TZ).replace(day=1).date() for d in range(s.days + 1)})
        tolls = {"volvo": 13800, "scania": 9800, "actros": 6900, "man": 4100, "daf": 7300}
        for key, tag in s.trucks.items():
            cc = s.cost_centres["Coastal operations" if key in ("actros", "man") else "Long-haul operations"]
            for m in months:
                last = (m.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
                s.db.add(MaintenanceCost(usergroup_id=s.gid, imei=tag.imei, cost_date=m, category="insurance", cost_centre_id=cc.id,
                                         description=f"Santam fleet insurance {m:%b %Y}", amount=Decimal("13850.00"), amortise_from=m, amortise_to=last))
                s.db.add(MaintenanceCost(usergroup_id=s.gid, imei=tag.imei, cost_date=last, category="other", cost_centre_id=cc.id,
                                         description=f"Toll fees {m:%b %Y}", amount=Decimal(str(round(tolls[key] * random.uniform(0.85, 1.12), 2)))))
            lic = date.fromisoformat(tag.attributes["licence_start"]["value"])
            s.db.add(MaintenanceCost(usergroup_id=s.gid, imei=tag.imei, cost_date=lic, category="licence", cost_centre_id=cc.id,
                                     description="Vehicle licence and permit", amount=Decimal("9450.00"), amortise_from=lic,
                                     amortise_to=lic.replace(year=lic.year + 1) - timedelta(days=1)))
        for key, days, what, amount in [("man", 61, "AARTO speeding fine – N2 Port Shepstone (92 in 80)", 1250),
                                        ("volvo", 27, "Overload fine – Mooi River weighbridge (axle 2)", 3500),
                                        ("daf", 12, "AARTO speeding fine – N1 Kroonstad", 750)]:
            s.db.add(MaintenanceCost(usergroup_id=s.gid, imei=s.trucks[key].imei, cost_date=(s.now - timedelta(days=days)).date(),
                                     category="fines", description=what, amount=Decimal(str(amount))))
        # A maintenance-due alert for the Volvo's A-service
        v = s.trucks["volvo"]
        s._alert(v, "maintenance_due", f"{v.description}: A-service every 40 000 km due",
                 f"A-service (oil and filters) for {v.description} is due.", s.now.replace(hour=4, minute=0) if s.now.hour >= 4 else s.now,
                 {"imei": v.imei, "schedule": "A-service every 40 000 km", "type": "A-service (oil and filters)",
                  "due_km": self.odo_at("volvo", s.now) + target_left["volvo"], "km_left": target_left["volvo"], "status": "Due"}, read=False)
        s.db.commit()


def reset(db, group) -> None:
    """Remove everything seed_demo created in the group."""
    gid = group.id
    tags = [t for t in db.query(BLETag).filter(BLETag.attributes.op("->>")("_created_usergroup_id") == str(gid))
            if (t.attributes or {}).get("_demo")]
    imeis, tag_ids = [t.imei for t in tags], [t.id for t in tags]
    if imeis:
        db.query(VehicleBreakdown).filter(VehicleBreakdown.imei.in_(imeis)).delete(synchronize_session=False)
        db.query(MaintenanceCost).filter(MaintenanceCost.usergroup_id == gid, MaintenanceCost.imei.in_(imeis)).delete(synchronize_session=False)
        db.query(VehicleMaintenance).filter(VehicleMaintenance.usergroup_id == gid, VehicleMaintenance.imei.in_(imeis)).delete(synchronize_session=False)
        db.query(PlaceVisit).filter(PlaceVisit.imei.in_(imeis)).delete(synchronize_session=False)
        db.query(PortalAlert).filter(PortalAlert.tag_id.in_(tag_ids)).delete(synchronize_session=False)
        db.query(GeofenceStatus).filter(GeofenceStatus.tag_id.in_(tag_ids)).delete(synchronize_session=False)
        db.query(POITrackerLink).filter(POITrackerLink.tracker_id.in_(tag_ids)).delete(synchronize_session=False)
        db.execute(text("DELETE FROM device_events WHERE imei = ANY(:i)"), {"i": imeis})
        db.query(Trip).filter(Trip.imei.in_(imeis)).delete(synchronize_session=False)
        db.query(TripBuilderState).filter(TripBuilderState.imei.in_(imeis)).delete(synchronize_session=False)
        for t in tags:
            db.delete(t)
    users = db.query(PortalUser).filter(PortalUser.usergroup_id == gid, PortalUser.email.like(f"%@{D.EMAIL_DOMAIN}")).all()
    uids = [u.id for u in users]
    if uids:
        db.query(ReportSchedule).filter(ReportSchedule.created_by.in_(uids)).delete(synchronize_session=False)
        db.query(NotificationRule).filter(NotificationRule.usergroup_id == gid,
                                          NotificationRule.name.in_(["Depot arrivals and departures", "Speeding and harsh driving"])).delete(synchronize_session=False)
        db.query(PortalUserRole).filter(PortalUserRole.user_id.in_(uids)).delete(synchronize_session=False)
        for u in users:
            db.delete(u)
    db.query(PortalRole).filter(PortalRole.usergroup_id == gid, PortalRole.name == "Fleet Manager", PortalRole.is_system == False).delete(synchronize_session=False)  # noqa: E712
    db.query(Driver).filter(Driver.usergroup_id == gid, Driver.employee_number.like("UT-%")).delete(synchronize_session=False)
    db.query(POI).filter(POI.usergroup_id == gid, POI.notes == DEMO_NOTE).delete(synchronize_session=False)
    db.query(PlaceGroup).filter(PlaceGroup.usergroup_id == gid, PlaceGroup.name.in_(list(D.PLACE_GROUPS))).delete(synchronize_session=False)
    db.query(TagCategory).filter(TagCategory.usergroup_id == gid, TagCategory.name.in_(list(D.VEHICLE_GROUPS))).delete(synchronize_session=False)
    db.query(SecurityGroup).filter(SecurityGroup.usergroup_id == gid, SecurityGroup.description.like(f"%{DEMO_NOTE}%")).delete(synchronize_session=False)
    db.query(TimeProfile).filter(TimeProfile.usergroup_id == gid, TimeProfile.name == "Long-haul shift").delete(synchronize_session=False)
    db.query(MaintenanceSchedule).filter(MaintenanceSchedule.usergroup_id == gid, MaintenanceSchedule.name.in_(
        ["A-service every 40 000 km", "B-service every 120 000 km", "Annual COF roadworthy"])).delete(synchronize_session=False)
    db.query(Workshop).filter(Workshop.usergroup_id == gid, Workshop.name.in_([
        "Volvo Trucks Durban (Bayhead)", "Scania Isando", "Mercedes-Benz Trucks Montague Gardens", "MAN Truck & Bus Pinetown",
        "DAF Trucks Germiston", "Supa Quick Commercial Jacobs"])).delete(synchronize_session=False)
    db.query(MaintenanceType).filter(MaintenanceType.usergroup_id == gid, MaintenanceType.name.in_([
        "A-service (oil and filters)", "B-service (major)", "Brake overhaul", "Tyre replacement", "Annual COF roadworthy"])).delete(synchronize_session=False)
    db.query(MaintenanceItem).filter(MaintenanceItem.usergroup_id == gid, MaintenanceItem.is_system == False, MaintenanceItem.name.in_([  # noqa: E712
        "Engine oil (40 L)", "Oil filter", "Fuel filters", "Air filter", "Gearbox oil", "Differential oil", "Brake linings (all axles)",
        "Brake drums", "Drive tyres (set of 8)", "Steer tyres (pair)", "Wheel alignment", "Grease fifth wheel and chassis", "Labour",
        "Certificate of fitness (COF) test"])).delete(synchronize_session=False)
    db.query(MaintenanceLookup).filter(MaintenanceLookup.usergroup_id == gid, or_(
        MaintenanceLookup.name.in_(["Truck tractor 6x4", "Long-haul operations", "Coastal operations", "Workshop overheads", "Volvo Trucks SA",
                                    "Scania South Africa", "Mercedes-Benz Trucks", "MAN Truck & Bus", "DAF Trucks SA", "Supa Quick",
                                    "OEM dealer", "Tyres", "Brakes and clutch"]))).delete(synchronize_session=False)
    db.commit()
    print(f"Removed the demo data: {len(tags)} vehicles, {len(users)} users.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--group", required=True, help="the user group's slug or name, e.g. utrack-logistics")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--reset", action="store_true", help="remove the demo data (and stop)")
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()
    random.seed(args.seed)
    db = SessionLocal()
    group = db.query(UserGroup).filter(or_(UserGroup.slug == args.group, UserGroup.name == args.group)).first()
    if not group:
        raise SystemExit(f"No user group '{args.group}'")
    if args.reset:
        reset(db, group)
        return
    if any((t.attributes or {}).get("_demo") for t in db.query(BLETag).filter(
            BLETag.attributes.op("->>")("_created_usergroup_id") == str(group.id))):
        raise SystemExit("This group already has demo data. Run with --reset first to replace it.")
    print(f"Seeding '{group.name}' with {args.days} days of demo data …")
    s = Seeder(db, group, args.days)
    s.setup()
    s.simulate()
    s.finish()
    print("\nDone. Sign in with any of these (password: %s):" % PASSWORD)
    for name, u in s.users.items():
        print(f"  {u.email:45} {name}")


if __name__ == "__main__":
    main()
