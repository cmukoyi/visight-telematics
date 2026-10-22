"""Security groups, roles, report logo and group timezone.

Revision ID: 068_add_access_control
Revises: 067_add_report_schedules
Create Date: 2026-10-22

Default roles are created per user group by app.services.access_service on
first use, which also assigns existing users a role matching their legacy
`role` column, so no data is moved here.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "068_add_access_control"
down_revision = "067_add_report_schedules"
branch_labels = None
depends_on = None


def _has_table(conn, name):
    return conn.execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": name}).scalar()


def upgrade():
    conn = op.get_bind()
    if not _has_table(conn, "security_groups"):
        op.create_table(
            "security_groups",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("usergroup_id", UUID(as_uuid=True), sa.ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("description", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("usergroup_id", "name", name="uq_security_group_name"),
        )
    if not _has_table(conn, "portal_roles"):
        op.create_table(
            "portal_roles",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("usergroup_id", UUID(as_uuid=True), sa.ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("description", sa.String(255), nullable=True),
            sa.Column("permissions", sa.JSON(), nullable=False),
            sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("usergroup_id", "name", name="uq_portal_role_name"),
        )
    op.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS role_id UUID REFERENCES portal_roles(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS security_group_id UUID REFERENCES security_groups(id) ON DELETE SET NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_portal_users_role_id ON portal_users (role_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_portal_users_security_group_id ON portal_users (security_group_id)")
    op.execute("ALTER TABLE tag_categories ADD COLUMN IF NOT EXISTS security_group_id UUID REFERENCES security_groups(id) ON DELETE SET NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tag_categories_security_group_id ON tag_categories (security_group_id)")
    op.execute("ALTER TABLE user_groups ADD COLUMN IF NOT EXISTS report_logo_data TEXT")
    op.execute("ALTER TABLE user_groups ADD COLUMN IF NOT EXISTS timezone VARCHAR(64)")
    # One alert per vehicle per type per day suits battery/offline alerts, but a
    # vehicle can enter and leave many places a day: exempt geofence alerts.
    op.execute("DROP INDEX IF EXISTS uq_portal_alert_per_day")
    op.execute(
        "CREATE UNIQUE INDEX uq_portal_alert_per_day ON portal_alerts "
        "(usergroup_id, tag_id, alert_type, DATE(created_at AT TIME ZONE 'UTC')) "
        "WHERE tag_id IS NOT NULL AND alert_type NOT IN ('geofence_entry', 'geofence_exit')"
    )


def downgrade():
    # (uq_portal_alert_per_day keeps the geofence exemption: re-adding it could fail on existing rows)
    op.execute("ALTER TABLE user_groups DROP COLUMN IF EXISTS timezone")
    op.execute("ALTER TABLE user_groups DROP COLUMN IF EXISTS report_logo_data")
    op.execute("ALTER TABLE tag_categories DROP COLUMN IF EXISTS security_group_id")
    op.execute("ALTER TABLE portal_users DROP COLUMN IF EXISTS security_group_id")
    op.execute("ALTER TABLE portal_users DROP COLUMN IF EXISTS role_id")
    op.drop_table("portal_roles")
    op.drop_table("security_groups")
