"""Add SMS fields to tag_packages, user_groups and portal_users.

tag_packages.sms_addon       — whether this package includes SMS alerts as an add-on
user_groups.sms_enabled      — whether this tenant has SMS alerts activated
user_groups.sms_monthly_limit — max SMS per month (NULL = no limit)
portal_users.phone_number          — E.164 mobile number for SMS
portal_users.sms_enabled           — master SMS on/off for this user
portal_users.notify_geofence_sms   — geofence alerts via SMS
portal_users.notify_battery_sms    — battery-low alerts via SMS
portal_users.notify_offline_sms    — tag-offline alerts via SMS

Revision ID: 031
Revises: 030
Create Date: 2026-05-02
"""
from alembic import op
import sqlalchemy as sa

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade():
    # tag_packages
    op.add_column("tag_packages", sa.Column("sms_addon", sa.Boolean(), nullable=False, server_default="false"))

    # user_groups
    op.add_column("user_groups", sa.Column("sms_enabled", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("user_groups", sa.Column("sms_monthly_limit", sa.Integer(), nullable=True))

    # portal_users
    op.add_column("portal_users", sa.Column("phone_number", sa.String(30), nullable=True))
    op.add_column("portal_users", sa.Column("sms_enabled", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("portal_users", sa.Column("notify_geofence_sms", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("portal_users", sa.Column("notify_battery_sms", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("portal_users", sa.Column("notify_offline_sms", sa.Boolean(), nullable=False, server_default="true"))


def downgrade():
    op.drop_column("portal_users", "notify_offline_sms")
    op.drop_column("portal_users", "notify_battery_sms")
    op.drop_column("portal_users", "notify_geofence_sms")
    op.drop_column("portal_users", "sms_enabled")
    op.drop_column("portal_users", "phone_number")
    op.drop_column("user_groups", "sms_monthly_limit")
    op.drop_column("user_groups", "sms_enabled")
    op.drop_column("tag_packages", "sms_addon")
