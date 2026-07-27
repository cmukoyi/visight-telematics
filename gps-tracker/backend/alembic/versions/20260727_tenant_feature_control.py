"""Tenant feature control - Admin portal manages customer dashboard features

Revision ID: tenant_feature_control
Revises: v2114_c2a_c3
Create Date: 2026-07-27

Add tenant-wide feature control to replace .env feature gates.
Allows admin portal to control which customer dashboard features are available
to all users in a tenant. Features are controlled via checkboxes in admin UI.

Features controlled:
- livemap: Live GPS tracking map
- history: Journey history with playback
- history-advanced: Movement Analytics (great-circle arcs, air legs, etc.)
- alerts: Alert configuration and notifications
- geofences: Geofence management
- reports: Reports and analytics
- management: Tag management
- floorplan: Indoor floor plan tracking
- settings: User settings and preferences

Logic:
- Tenant features = master switch (all users in tenant)
- User custom_features = per-user refinement
- effective_features = intersection(tenant_features, user_features)
- Default: all features enabled for backward compatibility

Reference: Admin portal tenant feature control implementation
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = 'tenant_feature_control'
down_revision = 'v2114_c2a_c3'
branch_labels = None
depends_on = None


def upgrade():
    # Create tenant_features table
    op.create_table(
        'tenant_features',
        sa.Column('id', UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('usergroup_id', UUID(as_uuid=True), sa.ForeignKey('user_groups.id', ondelete='CASCADE'), nullable=False),
        sa.Column('feature_name', sa.String(50), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('updated_by', UUID(as_uuid=True), sa.ForeignKey('admin_users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    
    # Add unique constraint to prevent duplicate feature entries per tenant
    op.create_unique_constraint('uq_tenant_feature', 'tenant_features', ['usergroup_id', 'feature_name'])
    
    # Add indexes for common queries
    op.create_index('ix_tenant_features_usergroup_id', 'tenant_features', ['usergroup_id'])
    op.create_index('ix_tenant_features_enabled', 'tenant_features', ['enabled'])
    
    # Populate with all features enabled for existing tenants (backward compatibility)
    # This ensures existing tenants continue to see all features they had before
    conn = op.get_bind()
    conn.execute(sa.text("""
        INSERT INTO tenant_features (usergroup_id, feature_name, enabled)
        SELECT 
            ug.id,
            feature,
            true
        FROM user_groups ug
        CROSS JOIN (
            VALUES 
                ('livemap'),
                ('history'),
                ('history-advanced'),
                ('alerts'),
                ('geofences'),
                ('reports'),
                ('management'),
                ('floorplan'),
                ('settings'),
                ('hive')
        ) AS features(feature)
        WHERE ug.is_active = true
        ON CONFLICT (usergroup_id, feature_name) DO NOTHING
    """))


def downgrade():
    op.drop_index('ix_tenant_features_enabled', table_name='tenant_features')
    op.drop_index('ix_tenant_features_usergroup_id', table_name='tenant_features')
    op.drop_constraint('uq_tenant_feature', 'tenant_features', type_='unique')
    op.drop_table('tenant_features')
