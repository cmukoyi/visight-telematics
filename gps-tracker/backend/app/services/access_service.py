"""Customer-portal access control — roles, permissions and security groups.

Within a user group (a customer company):

- a **role** is a named set of PERMISSIONS; a portal user holds one or more
  roles and may do whatever any of them allows. Admin roles (User Group
  Administrator) can do everything and see every vehicle.
- **Configuration is for administrators only**: the ADMIN_ONLY permissions
  (users, roles, security, vehicle setup, rules, themes, audit, ...) are never
  granted through a custom role — only the administrator role has them.
- a **security group** decides which vehicles a user sees: each vehicle group
  (tag category) belongs to a security group, and a user sees only the
  vehicles whose vehicle group is in the user's security group (unless a role
  grants security.all_vehicles).

The built-in roles are created per user group on first use and kept in step
with DEFAULT_ROLES (ensure_defaults); custom roles are the group's own. A
non-admin can only grant permissions they hold themselves (check_grant).
"""
from dataclasses import dataclass, field
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session, object_session

from app.models import BLETag, PortalRole, PortalUser, PortalUserRole, SecurityGroup, TagCategory

# Sections, in the order the role editor lists them
SECTIONS = ["Live tracking", "History", "Places", "Alerts", "Reports", "Maintenance", "Vehicles", "Users and security", "Configuration"]

# key: (label, section, what it allows — shown to admins in the role and user editors)
PERMISSIONS: dict = {
    "map.view":              ("Live map", "Live tracking", "See vehicles and where they are now on the Dashboard map."),
    "live.track":            ("Follow a vehicle live", "Live tracking", "Track a vehicle every few seconds with its trail, on the Dashboard and in Workspace."),
    "history.view":          ("Trips and routes", "History", "Open trips, replay routes and see start and end addresses in Workspace."),
    "events.view":           ("Vehicle events", "History", "List and plot events such as ignition, speeding and harsh braking."),
    "places.view":           ("See places", "Places", "View places, place groups and which vehicles are inside geofences."),
    "places.manage":         ("Create and edit places", "Places", "Draw, edit, import and delete places and place groups."),
    "places.arm":            ("Arm geofences", "Places", "Choose which vehicles raise entry and exit alerts for a place."),
    "inbox.view":            ("Inbox and alerts", "Alerts", "Receive alerts and read them in the Inbox."),
    "rules.manage":          ("Notification rules", "Alerts", "Create and edit notification rules, including email subscriptions."),
    "reports.view":          ("Run reports", "Reports", "Run, view and download reports."),
    "reports.schedule":      ("Schedule reports", "Reports", "Email reports to people on a schedule."),
    "analytics.manage":      ("Build analytics", "Reports", "Add and change Analytics pages, charts and Expressions (everyone who can run reports can view them)."),
    "maintenance.view":      ("See maintenance", "Maintenance", "See due and overdue maintenance, jobs, costs and fault codes (DTC)."),
    "maintenance.manage":    ("Record maintenance", "Maintenance", "Book, start and complete maintenance jobs and record their costs."),
    "maintenance.configure": ("Maintenance setup", "Configuration", "Maintenance schedules, types, items, workshops, cost centres and vehicle types."),
    "vehicles.manage":       ("Edit vehicles", "Vehicles", "Change vehicle details: description, registration, make, model, driver and vehicle group."),
    "vehicles.delete":       ("Delete vehicles", "Vehicles", "Remove vehicles and all their history."),
    "vehicle_groups.manage": ("Vehicle groups", "Vehicles", "Create and edit vehicle groups and choose their security group."),
    "data_exchange.manage":  ("Data Exchange", "Vehicles", "Link the user group to a Data Exchange to receive devices."),
    "users.view":            ("See users", "Users and security", "List users, their roles and when they last signed in."),
    "users.manage":          ("Add and edit users", "Users and security", "Add users, change their roles and security group, reset passwords, deactivate and delete them."),
    "roles.manage":          ("Roles", "Users and security", "Create and edit roles and what they allow."),
    "security.manage":       ("Security groups", "Users and security", "Create security groups and choose which vehicle groups they contain."),
    "security.all_vehicles": ("See vehicles in all security groups", "Vehicles", "See every vehicle, not only those in the user's own security group."),
    "audit.view":            ("Audit trail", "Users and security", "See who changed what, and when."),
    "events.manage":         ("Event types", "Configuration", "Rename event types, set their colours and manage event type groups."),
    "settings.manage":       ("User group settings", "Configuration", "Timezone and how long history is kept."),
    "theme.manage":          ("Custom themes and logos", "Configuration", "Colours, menu, font, logos and the platform name."),
}
ALL_PERMISSIONS = list(PERMISSIONS)

# Everything under Configuration: only administrators may do these
ADMIN_ONLY = {
    "vehicles.manage", "vehicles.delete", "vehicle_groups.manage", "data_exchange.manage",
    "users.view", "users.manage", "roles.manage", "security.manage", "audit.view",
    "rules.manage", "events.manage", "settings.manage", "theme.manage", "maintenance.configure",
}
# What a role can be given (the role builder lists these)
ROLE_PERMISSIONS = [p for p in ALL_PERMISSIONS if p not in ADMIN_ONLY]

# Permissions that came with an older, broader one (expand_legacy, migration 073)
LEGACY_IMPLIES = {
    "map.view": ["live.track"],
    "history.view": ["events.view"],
    "places.manage": ["places.arm"],
    "vehicles.manage": ["vehicles.delete", "vehicle_groups.manage"],
    "users.manage": ["users.view"],
    "security.manage": ["roles.manage"],
    "settings.manage": ["theme.manage", "data_exchange.manage", "events.manage"],
    "rules.manage": ["events.manage"],
}

ADMIN_ROLE = "User Group Administrator"
# name: (description, permissions, is_admin)
DEFAULT_ROLES: dict = {
    ADMIN_ROLE: ("Everything, including Configuration, and every vehicle", ALL_PERMISSIONS, True),
    "Operator": ("Day-to-day tracking: live map, live tracking, trips, events, places, geofences, alerts and reports",
                 ["map.view", "live.track", "history.view", "events.view", "places.view", "places.manage", "places.arm",
                  "inbox.view", "reports.view", "maintenance.view"], False),
    "Mapping User": ("Live map, live tracking, trips and places",
                     ["map.view", "live.track", "history.view", "places.view", "places.manage", "places.arm"], False),
    "Maintenance User": ("Vehicle maintenance, positions, trips and events, alerts and reports",
                         ["map.view", "history.view", "events.view", "inbox.view", "reports.view", "reports.schedule",
                          "maintenance.view", "maintenance.manage"], False),
    "Reporting User": ("Runs and schedules reports, builds analytics, and receives alerts",
                       ["reports.view", "reports.schedule", "analytics.manage", "inbox.view"], False),
    "MZone Driver": ("Sees their vehicles on the map, live, with their trips",
                     ["map.view", "live.track", "history.view"], False),
}
# legacy PortalUser.role → default role
_LEGACY_ROLE = {"admin": ADMIN_ROLE, "system_admin": ADMIN_ROLE, "manager": "Operator",
                "reporter": "Reporting User", "custom": "Operator", "api_only": "Reporting User"}

# Classic dashboard: tabs each permission unlocks, and the permission its
# write actions (_user_can_manage feature keys) need.
CLASSIC_TABS = {
    "map.view": ["livemap", "assets"],
    "history.view": ["trips"],
    "places.view": ["locations"],
    "vehicles.manage": ["asset-mgmt"],
    "users.manage": ["users"],
    "settings.manage": ["settings"],
    "reports.view": ["reports-activity", "reports-alerts", "reports-geofence", "reports-battery"],
    "reports.schedule": ["reports-subscriptions"],
}
CLASSIC_MANAGE = {"asset-mgmt": "vehicles.manage", "users": "users.manage",
                  "locations": "places.manage", "settings": "settings.manage"}


def expand_legacy(perms: Iterable[str]) -> list:
    """Old permission keys plus the newer ones they used to cover, limited to known permissions."""
    out = set(perms)
    for p in list(out):
        out.update(LEGACY_IMPLIES.get(p, []))
    return [p for p in ALL_PERMISSIONS if p in out]


def role_ids(db: Session, user: PortalUser) -> list:
    """IDs of the roles a user holds (falls back to the legacy single role_id)."""
    ids = [rid for (rid,) in db.query(PortalUserRole.role_id).filter(PortalUserRole.user_id == user.id).all()]
    if not ids and user.role_id:
        ids = [user.role_id]
    return ids


def set_roles(db: Session, user: PortalUser, roles: list) -> None:
    """Give a user exactly these roles (role_id keeps the first, for older code). Flushes only."""
    db.query(PortalUserRole).filter(PortalUserRole.user_id == user.id).delete(synchronize_session=False)
    for r in roles:
        db.add(PortalUserRole(user_id=user.id, role_id=r.id))
    user.role_id = roles[0].id if roles else None
    admin = any(r.is_admin for r in roles)
    user.role = "admin" if admin else "custom"
    user.is_group_admin = admin          # the legacy flag follows the roles, so roles always decide
    user.custom_features = None
    db.flush()


def ensure_defaults(db: Session, usergroup_id) -> None:
    """Create any missing built-in roles (and keep their permissions in step with DEFAULT_ROLES),
    and give role-less users the role matching their legacy `role`. Flushes only."""
    roles = {r.name: r for r in db.query(PortalRole).filter(PortalRole.usergroup_id == usergroup_id).all()}
    for name, (description, perms, is_admin) in DEFAULT_ROLES.items():
        role = roles.get(name)
        if role is None:
            roles[name] = PortalRole(usergroup_id=usergroup_id, name=name, description=description,
                                     permissions=list(perms), is_admin=is_admin, is_system=True)
            db.add(roles[name])
        elif role.is_system and (list(role.permissions or []) != list(perms) or role.description != description):
            role.permissions, role.description, role.is_admin = list(perms), description, is_admin
    # Built-in roles that no longer exist: delete if nobody holds them, else keep as the group's own role
    for name, role in list(roles.items()):
        if role.is_system and name not in DEFAULT_ROLES:
            if db.query(PortalUserRole).filter(PortalUserRole.role_id == role.id).first() or \
                    db.query(PortalUser.id).filter(PortalUser.role_id == role.id).first():
                role.is_system = False
                role.permissions = [p for p in role.permissions or [] if p not in ADMIN_ONLY]
            else:
                db.delete(role)
                del roles[name]
    db.flush()
    for user in db.query(PortalUser).filter(PortalUser.usergroup_id == usergroup_id, PortalUser.role_id.is_(None)).all():
        if db.query(PortalUserRole).filter(PortalUserRole.user_id == user.id).first():
            continue
        legacy = ADMIN_ROLE if user.is_group_admin else _LEGACY_ROLE.get((user.role or "admin").lower(), "Operator")
        user.role_id = roles[legacy].id
        db.add(PortalUserRole(user_id=user.id, role_id=user.role_id))
    db.flush()


@dataclass
class Access:
    user: PortalUser
    roles: list = field(default_factory=list)
    permissions: set = field(default_factory=set)
    is_admin: bool = False

    @property
    def role(self) -> Optional[PortalRole]:
        return self.roles[0] if self.roles else None

    def can(self, permission: str) -> bool:
        return self.is_admin or permission in self.permissions

    def require(self, permission: str) -> None:
        if not self.can(permission):
            raise HTTPException(status_code=403, detail=f"Your roles don't allow this ({PERMISSIONS[permission][0].lower()})")

    def require_any(self, *permissions: str) -> None:
        if not any(self.can(p) for p in permissions):
            self.require(permissions[0])

    def check_grant(self, permissions: Iterable[str], admin: bool = False) -> None:
        """A non-admin may only hand out permissions they hold themselves, and never full admin."""
        if self.is_admin:
            return
        if admin:
            raise HTTPException(status_code=403, detail="Only a User Group Administrator can give the administrator role")
        missing = [PERMISSIONS[p][0] for p in permissions if p in PERMISSIONS and (p not in self.permissions or p in ADMIN_ONLY)]
        if missing:
            raise HTTPException(status_code=403, detail=f"You can't give permissions you don't have: {', '.join(missing)}")

    def visible_categories(self, db: Session) -> Optional[set]:
        """Vehicle-group names this user may see, or None for all."""
        if self.is_admin or "security.all_vehicles" in self.permissions:
            return None
        if not self.user.security_group_id:
            return set()
        return {name for (name,) in db.query(TagCategory.name).filter(
            TagCategory.usergroup_id == self.user.usergroup_id, TagCategory.is_active == True,  # noqa: E712
            TagCategory.security_group_id == self.user.security_group_id).all()}

    def visible_imeis(self, db: Session) -> Optional[set]:
        """IMEIs of the vehicles this user may see, or None for every vehicle in the group."""
        names = self.visible_categories(db)
        if names is None:
            return None
        if not names:
            return set()
        wanted = {n.lower() for n in names}
        tags = db.query(BLETag.imei, BLETag.attributes).filter(
            BLETag.attributes.op("->>")("_created_usergroup_id") == str(self.user.usergroup_id)).all()
        return {imei for imei, attrs in tags
                if (((attrs or {}).get("category") or {}).get("value") or "").lower() in wanted}

    def can_see(self, db: Session, imei: str) -> bool:
        visible = self.visible_imeis(db)
        return visible is None or imei in visible


def for_user(user: PortalUser, db: Optional[Session] = None) -> Access:
    """The user's roles, combined permissions and admin status (creating default roles if needed)."""
    db = db or object_session(user)
    if db is None:
        return Access(user=user, is_admin=bool(user.is_group_admin))
    ids = role_ids(db, user)
    if not ids:
        ensure_defaults(db, user.usergroup_id)
        db.commit()
        ids = role_ids(db, user)
    roles = db.query(PortalRole).filter(PortalRole.id.in_(ids)).all() if ids else []
    roles.sort(key=lambda r: (not r.is_admin, r.name.lower()))
    is_admin = bool(user.is_group_admin or any(r.is_admin for r in roles) or (not roles and user.role == "system_admin"))
    perms = set(ALL_PERMISSIONS) if is_admin else {p for r in roles for p in (r.permissions or []) if p in PERMISSIONS and p not in ADMIN_ONLY}
    return Access(user=user, roles=roles, permissions=perms, is_admin=is_admin)


def profile(db: Session, access: Access) -> dict:
    """Roles, permissions and security group for the login and /me responses."""
    sg = db.get(SecurityGroup, access.user.security_group_id) if access.user.security_group_id else None
    names = [r.name for r in access.roles]
    return {
        "role_id": str(access.role.id) if access.role else None,
        "role_name": ", ".join(names) if names else ("Administrator" if access.is_admin else None),
        "role_ids": [str(r.id) for r in access.roles],
        "role_names": names,
        "permissions": sorted(access.permissions),
        "is_admin": access.is_admin,
        "security_group_id": str(sg.id) if sg else None,
        "security_group_name": sg.name if sg else None,
        "language": user_language(db, access.user),
    }


def user_language(db: Session, user: PortalUser) -> str:
    """The user's own language, else their user group's default, else English."""
    if user.language:
        return user.language
    from app.models import UserGroup
    group = db.get(UserGroup, user.usergroup_id)
    return (group.default_language if group and group.default_language else None) or "en"


def admin_count(db: Session, usergroup_id, exclude_user_id=None) -> int:
    """Active users in the group with administrator access (by role or the legacy flag)."""
    n = 0
    for user in db.query(PortalUser).filter(PortalUser.usergroup_id == usergroup_id, PortalUser.is_active == True).all():  # noqa: E712
        if exclude_user_id is not None and str(user.id) == str(exclude_user_id):
            continue
        if for_user(user, db).is_admin:
            n += 1
    return n
