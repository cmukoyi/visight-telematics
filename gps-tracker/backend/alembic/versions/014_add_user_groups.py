"""add user_groups and portal_users tables for customer portal tenancy

Revision ID: 014
Revises: 013
Create Date: 2026-04-13

UserGroup  — one row per customer company / tenant.
PortalUser — users who can log in to the customer portal, scoped to a group.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_groups',
        sa.Column('id',         UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name',       sa.String(200), nullable=False, unique=True),
        sa.Column('slug',       sa.String(100), nullable=False, unique=True),
        sa.Column('is_active',  sa.Boolean(),   nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        'portal_users',
        sa.Column('id',              UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('usergroup_id',    UUID(as_uuid=True), sa.ForeignKey('user_groups.id', ondelete='CASCADE'), nullable=False),
        sa.Column('email',           sa.String(255), nullable=False, unique=True),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('first_name',      sa.String(100), nullable=True),
        sa.Column('last_name',       sa.String(100), nullable=True),
        sa.Column('is_active',       sa.Boolean(),   nullable=False, server_default='true'),
        sa.Column('is_group_admin',  sa.Boolean(),   nullable=False, server_default='false'),
        sa.Column('created_at',      sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at',      sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_portal_users_email', 'portal_users', ['email'], unique=True)


def downgrade():
    op.drop_index('ix_portal_users_email', table_name='portal_users')
    op.drop_table('portal_users')
    op.drop_table('user_groups')
