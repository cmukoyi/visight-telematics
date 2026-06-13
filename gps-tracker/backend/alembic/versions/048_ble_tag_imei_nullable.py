"""Make ble_tags.imei nullable for pure-BLE tags (no IMEI)

GPS trackers (tracksolid, scope, series_3) keep imei NOT NULL via a check
constraint. BLE-only tags (tag_type = 'ble') identify by mac_address instead.

Revision ID: 048_ble_tag_imei_nullable
Revises: 047_hive_outlier_audit
Create Date: 2026-06-13
"""
from alembic import op
import sqlalchemy as sa

revision = '048_ble_tag_imei_nullable'
down_revision = '047_hive_outlier_audit'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Drop the NOT NULL constraint on imei
    op.alter_column('ble_tags', 'imei', nullable=True)

    # 2. Add a check constraint: GPS types require imei, BLE type requires mac_address
    op.create_check_constraint(
        'chk_ble_tags_identifier',
        'ble_tags',
        "(tag_type = 'ble' AND mac_address IS NOT NULL) OR "
        "(tag_type != 'ble' AND imei IS NOT NULL)"
    )

    # 3. Create index on mac_address for fast pareto_bridge lookups
    op.create_index('ix_ble_tags_mac_address', 'ble_tags', ['mac_address'],
                    unique=False,
                    postgresql_where=sa.text("mac_address IS NOT NULL"))


def downgrade():
    op.drop_index('ix_ble_tags_mac_address', table_name='ble_tags')
    op.drop_constraint('chk_ble_tags_identifier', 'ble_tags', type_='check')
    op.alter_column('ble_tags', 'imei', nullable=False)
