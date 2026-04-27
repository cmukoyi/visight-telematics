"""Add verification PIN and BLE tags tables

Revision ID: 001
Revises: 
Create Date: 2024-02-28

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '001'
down_revision = '000'
branch_labels = None
depends_on = None


def column_exists(table_name, column_name):
    """Check if a column exists in a table"""
    bind = op.get_bind()
    result = bind.execute(text(
        """
        SELECT EXISTS (
            SELECT FROM information_schema.columns 
            WHERE table_name = :table_name 
            AND column_name = :column_name
        );
        """
    ), {"table_name": table_name, "column_name": column_name})
    return result.scalar()


def table_exists(table_name):
    """Check if a table exists"""
    bind = op.get_bind()
    result = bind.execute(text(
        """
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = :table_name
        );
        """
    ), {"table_name": table_name})
    return result.scalar()


def upgrade():
    # Update users table to add phone and email_verified columns (only if they don't exist)
    if not column_exists('users', 'phone'):
        op.add_column('users', sa.Column('phone', sa.String(20), nullable=True))
    
    if not column_exists('users', 'email_verified'):
        op.add_column('users', sa.Column('email_verified', sa.Boolean(), default=False))
    
    # Make hashed_password nullable for passwordless users (only if it's not already nullable)
    try:
        op.alter_column('users', 'hashed_password', nullable=True)
    except:
        pass  # Already nullable
    
    # Create verification_pins table (only if it doesn't exist)
    if not table_exists('verification_pins'):
        op.create_table(
            'verification_pins',
            sa.Column('id', UUID(as_uuid=True), primary_key=True),
            sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('email', sa.String(255), nullable=False, index=True),
            sa.Column('pin', sa.String(6), nullable=False),
            sa.Column('is_used', sa.Boolean(), default=False),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now())
        )
        
        # Create indexes for verification_pins
        op.create_index('idx_verification_pins_email', 'verification_pins', ['email'])
        op.create_index('idx_verification_pins_expires', 'verification_pins', ['expires_at'])
    
    # Create ble_tags table (only if it doesn't exist)
    if not table_exists('ble_tags'):
        op.create_table(
            'ble_tags',
            sa.Column('id', UUID(as_uuid=True), primary_key=True),
            sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('imei', sa.String(50), unique=True, nullable=False, index=True),
            sa.Column('device_name', sa.String(100), nullable=True),
            sa.Column('device_model', sa.String(100), nullable=True),
            sa.Column('mac_address', sa.String(17), nullable=True),
            sa.Column('is_active', sa.Boolean(), default=True),
            sa.Column('last_seen', sa.DateTime(timezone=True), nullable=True),
            sa.Column('latitude', sa.String(50), nullable=True),
            sa.Column('longitude', sa.String(50), nullable=True),
            sa.Column('battery_level', sa.Integer(), nullable=True),
            sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now())
        )
        
        # Create indexes for ble_tags
        op.create_index('idx_ble_tags_user_id', 'ble_tags', ['user_id'])
        op.create_index('idx_ble_tags_imei', 'ble_tags', ['imei'])


def downgrade():
    op.drop_index('idx_ble_tags_imei', 'ble_tags')
    op.drop_index('idx_ble_tags_user_id', 'ble_tags')
    op.drop_index('idx_verification_pins_expires', 'verification_pins')
    op.drop_index('idx_verification_pins_email', 'verification_pins')
    
    op.drop_table('ble_tags')
    op.drop_table('verification_pins')
    
    op.alter_column('users', 'hashed_password', nullable=False)
    op.drop_column('users', 'email_verified')
    op.drop_column('users', 'phone')
