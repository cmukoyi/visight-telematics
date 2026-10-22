"""Place groups, event type names/groups, event notification rules, user last login/activity.

Revision ID: 071_add_place_and_event_groups
Revises: 070_add_trip_addresses
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "071_add_place_and_event_groups"
down_revision = "070_add_trip_addresses"
branch_labels = None
depends_on = None


def _has_table(name):
    return op.get_bind().execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": name}).scalar()


def upgrade():
    if not _has_table("place_groups"):
        op.create_table(
            "place_groups",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("usergroup_id", UUID(as_uuid=True), sa.ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("color", sa.String(20), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("usergroup_id", "name", name="uq_place_group_name"),
        )
    if not _has_table("event_type_settings"):
        op.create_table(
            "event_type_settings",
            sa.Column("usergroup_id", UUID(as_uuid=True), sa.ForeignKey("user_groups.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("code", sa.String(40), primary_key=True),
            sa.Column("label", sa.String(120), nullable=True),
            sa.Column("color", sa.String(20), nullable=True),
        )
    if not _has_table("event_type_groups"):
        op.create_table(
            "event_type_groups",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("usergroup_id", UUID(as_uuid=True), sa.ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("codes", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("usergroup_id", "name", name="uq_event_type_group_name"),
        )
    op.execute("ALTER TABLE pois ADD COLUMN IF NOT EXISTS place_group_id UUID REFERENCES place_groups(id) ON DELETE SET NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_pois_place_group_id ON pois (place_group_id)")
    op.execute("ALTER TABLE notification_rules ADD COLUMN IF NOT EXISTS place_group_ids JSON")
    op.execute("ALTER TABLE notification_rules ADD COLUMN IF NOT EXISTS event_group_id UUID REFERENCES event_type_groups(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ")
    op.execute("ALTER TABLE portal_users ADD COLUMN IF NOT EXISTS last_active_at TIMESTAMPTZ")
    # Event-rule alerts (event_<code>) can happen many times a day, like geofence alerts
    op.execute("DROP INDEX IF EXISTS uq_portal_alert_per_day")
    op.execute(
        "CREATE UNIQUE INDEX uq_portal_alert_per_day ON portal_alerts "
        "(usergroup_id, tag_id, alert_type, DATE(created_at AT TIME ZONE 'UTC')) "
        "WHERE tag_id IS NOT NULL AND alert_type NOT IN ('geofence_entry', 'geofence_exit') "
        "AND alert_type NOT LIKE 'event\\_%'"
    )


def downgrade():
    op.execute("ALTER TABLE portal_users DROP COLUMN IF EXISTS last_active_at")
    op.execute("ALTER TABLE portal_users DROP COLUMN IF EXISTS last_login_at")
    op.execute("ALTER TABLE notification_rules DROP COLUMN IF EXISTS event_group_id")
    op.execute("ALTER TABLE notification_rules DROP COLUMN IF EXISTS place_group_ids")
    op.execute("ALTER TABLE pois DROP COLUMN IF EXISTS place_group_id")
    op.drop_table("event_type_groups")
    op.drop_table("event_type_settings")
    op.drop_table("place_groups")
