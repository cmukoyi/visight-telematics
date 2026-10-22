"""Several roles per portal user, finer permissions, portal audit trail; drop user_groups.email_domain.

Revision ID: 073_roles_audit_domain
Revises: 072_event_rule_codes_theme
Create Date: 2026-10-23
"""
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "073_roles_audit_domain"
down_revision = "072_event_rule_codes_theme"
branch_labels = None
depends_on = None

# Old permission → the finer ones it used to cover (access_service.LEGACY_IMPLIES)
IMPLIES = {
    "map.view": ["live.track"],
    "history.view": ["events.view"],
    "places.manage": ["places.arm"],
    "vehicles.manage": ["vehicles.delete", "vehicle_groups.manage"],
    "users.manage": ["users.view"],
    "security.manage": ["roles.manage"],
    "settings.manage": ["theme.manage", "data_exchange.manage", "events.manage"],
    "rules.manage": ["events.manage"],
}


def _has_table(name):
    return op.get_bind().execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": name}).scalar()


def _has_column(table, column):
    return op.get_bind().execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
        {"t": table, "c": column}).first() is not None


def upgrade():
    bind = op.get_bind()
    if not _has_table("portal_user_roles"):
        op.create_table(
            "portal_user_roles",
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("portal_users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("role_id", UUID(as_uuid=True), sa.ForeignKey("portal_roles.id", ondelete="CASCADE"), primary_key=True),
        )
        op.create_index("ix_portal_user_roles_role_id", "portal_user_roles", ["role_id"])
    bind.execute(text(
        "INSERT INTO portal_user_roles (user_id, role_id) SELECT id, role_id FROM portal_users "
        "WHERE role_id IS NOT NULL ON CONFLICT DO NOTHING"))

    # Custom roles keep what they could do before the permissions were split
    for rid, perms in bind.execute(text("SELECT id, permissions FROM portal_roles WHERE NOT is_system")).fetchall():
        perms = perms if isinstance(perms, list) else json.loads(perms or "[]")
        out = list(perms)
        for p in perms:
            out += [x for x in IMPLIES.get(p, []) if x not in out]
        if out != perms:
            bind.execute(text("UPDATE portal_roles SET permissions = CAST(:p AS json) WHERE id = :id"),
                         {"p": json.dumps(out), "id": rid})

    if not _has_table("portal_audit_logs"):
        op.create_table(
            "portal_audit_logs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("usergroup_id", UUID(as_uuid=True), sa.ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("portal_users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("user_email", sa.String(255), nullable=True),
            sa.Column("user_name", sa.String(255), nullable=True),
            sa.Column("action", sa.String(30), nullable=False),
            sa.Column("area", sa.String(50), nullable=False),
            sa.Column("summary", sa.String(500), nullable=False),
            sa.Column("resource_id", sa.String(100), nullable=True),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.Column("outcome", sa.String(20), nullable=False, server_default="success"),
            sa.Column("ip_address", sa.String(45), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_portal_audit_group_created", "portal_audit_logs", ["usergroup_id", "created_at"])

    if _has_column("user_groups", "email_domain"):
        op.drop_column("user_groups", "email_domain")


def downgrade():
    if not _has_column("user_groups", "email_domain"):
        op.add_column("user_groups", sa.Column("email_domain", sa.String(500), nullable=True))
    if _has_table("portal_audit_logs"):
        op.drop_table("portal_audit_logs")
    if _has_table("portal_user_roles"):
        op.drop_table("portal_user_roles")
