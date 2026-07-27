"""Add developers feature to existing tenant_features

Revision ID: add_developers_feature
Revises: tenant_feature_control
Create Date: 2026-07-27

Add 'developers' feature to all existing tenants (enabled by default for backward compatibility)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_developers_feature'
down_revision = 'tenant_feature_control'
branch_labels = None
depends_on = None


def upgrade():
    # Add 'developers' feature to all existing tenants (enabled by default)
    conn = op.get_bind()
    conn.execute(sa.text("""
        INSERT INTO tenant_features (usergroup_id, feature_name, enabled)
        SELECT 
            ug.id,
            'developers',
            true
        FROM user_groups ug
        WHERE ug.is_active = true
        ON CONFLICT (usergroup_id, feature_name) DO NOTHING
    """))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text("""
        DELETE FROM tenant_features 
        WHERE feature_name = 'developers'
    """))
