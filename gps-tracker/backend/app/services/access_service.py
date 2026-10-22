"""Customer-portal access control — roles, permissions and security groups.

Within a user group (a customer company):

- a **role** is a named set of PERMISSIONS; every portal user has one.
  Admin roles (User Group Administrator) can do everything and see every vehicle.
- a **security group** decides which vehicles a user sees: each vehicle group
  (tag category) belongs to a security group, and a non-admin user sees only
  the vehicles whose vehicle group is in the user's security group.

The default roles are created per user group on first use (ensure_defaults),
which also gives existing users the role matching their legacy `role` column.
"""
from dataclasses import dataclass, field
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session, object_session

from app.models import BLETag, PortalRole, PortalUser, SecurityGroup, TagCategory

# key: (label, section)
PERMISSIONS: dict = {
    "map.view":         ("View vehicles on the live map", "Tracking"),
    "history.view":     ("View trips, routes and events", "Tracking"),
    "places.view":      ("View places (geofences)", "Places"),
    "places.manage":    ("Create, edit and arm places", "Places"),
    "inbox.view":       ("Receive and view alerts", "Alerts"),
    "reports.view":     ("Run and download reports", "Reports"),
    "reports.schedule": ("Schedule emailed reports", "Reports"),
    "vehicles.manage":  ("Edit vehicles and vehicle groups", "Administration"),
    "users.manage":     ("Manage users", "Administration"),
    "security.manage":  ("Manage security groups and roles", "Administration"),
    "settings.manage":  ("Change theme, logos, timezone and Data Exchange", "Administration"),
}
ALL_PERMISSIONS = list(PERMISSIONS)

ADMIN_ROLE = "User Group Administrator"
# name: (description, permissions, is_admin)
DEFAULT_ROLES: dict = {
    ADMIN_ROLE: ("Full access to everything in the user group, including all vehicles", ALL_PERMISSIONS, True),
    "Operator": ("Day-to-day tracking: live map, trips, places and alerts",
                 ["map.view", "history.view", "places.view", "places.manage", "inbox.view", "reports.view"], False),
    "Mapping User": ("Live map, trip history and places",
                     ["map.view", "history.view", "places.view", "places.manage"], False),
    "Maintenance User": ("Vehicle details, live map, alerts and reports",
                         ["map.view", "history.view", "vehicles.manage", "inbox.view", "reports.view"], False),
    "Reporting User": ("Runs and schedules reports",
                       ["reports.view", "reports.schedule", "inbox.view"], False),
    "MZone Driver": ("Sees the vehicles in their security group on the map",
                     ["map.view", "history.view"], False),
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


def ensure_defaults(db: Session, usergroup_id) -> None:
    """Create any missing default roles for the group and give role-less users one. Flushes only."""
    roles = {r.name: r for r in db.query(PortalRole).filter(PortalRole.usergroup_id == usergroup_id).all()}
    for name, (description, perms, is_admin) in DEFAULT_ROLES.items():
        if name not in roles:
            roles[name] = PortalRole(usergroup_id=usergroup_id, name=name, description=description,
                                     permissions=list(perms), is_admin=is_admin, is_system=True)
            db.add(roles[name])
    db.flush()
    for user in db.query(PortalUser).filter(PortalUser.usergroup_id == usergroup_id, PortalUser.role_id.is_(None)).all():
        legacy = ADMIN_ROLE if user.is_group_admin else _LEGACY_ROLE.get((user.role or "admin").lower(), "Operator")
        user.role_id = roles[legacy].id
    db.flush()


@dataclass
class Access:
    user: PortalUser
    role: Optional[PortalRole]
    permissions: set = field(default_factory=set)
    is_admin: bool = False

    def can(self, permission: str) -> bool:
        return self.is_admin or permission in self.permissions

    def require(self, permission: str) -> None:
        if not self.can(permission):
            raise HTTPException(status_code=403, detail=f"Your role doesn't allow this ({PERMISSIONS[permission][0].lower()})")

    def visible_categories(self, db: Session) -> Optional[set]:
        """Vehicle-group names this user may see, or None for all."""
        if self.is_admin:
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
    """The user's role, permissions and admin status (creating default roles if needed)."""
    db = db or object_session(user)
    if user.role_id is None and db is not None:
        ensure_defaults(db, user.usergroup_id)
        db.commit()
    role = db.get(PortalRole, user.role_id) if (db is not None and user.role_id) else None
    is_admin = bool(user.is_group_admin or (role and role.is_admin) or (role is None and user.role == "system_admin"))
    perms = set(ALL_PERMISSIONS) if is_admin else {p for p in (role.permissions if role else []) if p in PERMISSIONS}
    return Access(user=user, role=role, permissions=perms, is_admin=is_admin)


def profile(db: Session, access: Access) -> dict:
    """Role, permissions and security group for the login and /me responses."""
    sg = db.get(SecurityGroup, access.user.security_group_id) if access.user.security_group_id else None
    return {
        "role_id": str(access.role.id) if access.role else None,
        "role_name": access.role.name if access.role else ("Administrator" if access.is_admin else None),
        "permissions": sorted(access.permissions),
        "is_admin": access.is_admin,
        "security_group_id": str(sg.id) if sg else None,
        "security_group_name": sg.name if sg else None,
    }
