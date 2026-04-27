"""Create admin models tables

Revision ID: add_admin_models
Revises: 009
Create Date: 2025-03-11

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'add_admin_models'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade():
    # Create admin_users table
    op.create_table(
        'admin_users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('username', sa.String(50), nullable=False, unique=True),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('full_name', sa.String(100)),
        sa.Column('role', sa.String(20), nullable=False, server_default='viewer'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('last_login', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_admin_users_username', 'admin_users', ['username'])
    op.create_index('ix_admin_users_email', 'admin_users', ['email'])

    # Create app_logs table
    op.create_table(
        'app_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.String(36)),
        sa.Column('admin_user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('level', sa.String(10), nullable=False, server_default='INFO'),
        sa.Column('category', sa.String(50)),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('context', postgresql.JSON()),
        sa.Column('stack_trace', sa.Text()),
        sa.Column('source', sa.String(100)),
        sa.Column('ip_address', sa.String(45)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['admin_user_id'], ['admin_users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_app_logs_user_id', 'app_logs', ['user_id'])
    op.create_index('ix_app_logs_level', 'app_logs', ['level'])
    op.create_index('ix_app_logs_category', 'app_logs', ['category'])
    op.create_index('ix_app_logs_created_at', 'app_logs', ['created_at'])
    op.create_index('ix_app_logs_created_level', 'app_logs', ['created_at', 'level'])
    op.create_index('ix_app_logs_user_created', 'app_logs', ['user_id', 'created_at'])
    op.create_index('ix_app_logs_category_created', 'app_logs', ['category', 'created_at'])

    # Create audit_logs table
    op.create_table(
        'audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('admin_user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('resource_type', sa.String(50)),
        sa.Column('resource_id', sa.String(100)),
        sa.Column('old_value', postgresql.JSON()),
        sa.Column('new_value', postgresql.JSON()),
        sa.Column('ip_address', sa.String(45)),
        sa.Column('description', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['admin_user_id'], ['admin_users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_logs_admin_created', 'audit_logs', ['admin_user_id', 'created_at'])
    op.create_index('ix_audit_logs_resource', 'audit_logs', ['resource_type', 'resource_id'])
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'])

    # Create billing_data table
    op.create_table(
        'billing_data',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('date', sa.DateTime(timezone=True), nullable=False, unique=True),
        sa.Column('total_users', sa.Integer(), server_default='0'),
        sa.Column('active_users', sa.Integer(), server_default='0'),
        sa.Column('total_imeis', sa.Integer(), server_default='0'),
        sa.Column('active_devices_by_user', postgresql.JSON()),
        sa.Column('imei_to_user', postgresql.JSON()),
        sa.Column('user_device_count', postgresql.JSON()),
        sa.Column('meta_data', postgresql.JSON()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_billing_data_date', 'billing_data', ['date'])

    # Create billing_transactions table
    op.create_table(
        'billing_transactions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.String(36)),
        sa.Column('transaction_type', sa.String(50)),
        sa.Column('imei', sa.String(50)),
        sa.Column('amount', sa.Float(), server_default='0'),
        sa.Column('currency', sa.String(3), server_default='USD'),
        sa.Column('description', sa.Text()),
        sa.Column('meta_data', postgresql.JSON()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_billing_transactions_user_id', 'billing_transactions', ['user_id'])
    op.create_index('ix_billing_transactions_imei', 'billing_transactions', ['imei'])
    op.create_index('ix_billing_transactions_user_date', 'billing_transactions', ['user_id', 'created_at'])
    op.create_index('ix_billing_transactions_type_date', 'billing_transactions', ['transaction_type', 'created_at'])


def downgrade():
    op.drop_table('billing_transactions')
    op.drop_table('billing_data')
    op.drop_table('audit_logs')
    op.drop_table('app_logs')
    op.drop_table('admin_users')
