"""Add internationalization (i18n) tables for multi-language support

Creates tables for languages, translation keys, and translations.
Adds language preferences to users and usergroups.
Seeds initial English language and common translation keys.

Revision ID: 049_add_i18n_tables
Revises: 048_ble_tag_imei_nullable
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column

revision = '049_add_i18n_tables'
down_revision = '048_ble_tag_imei_nullable'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create languages table
    op.create_table(
        'languages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(5), nullable=False, unique=True, index=True),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    
    # 2. Create translation_keys table
    op.create_table(
        'translation_keys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(255), nullable=False, unique=True, index=True),
        sa.Column('category', sa.String(50), nullable=True),
        sa.Column('context', sa.Text(), nullable=True),
        sa.Column('default_text', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_translation_keys_category', 'translation_keys', ['category'])
    
    # 3. Create translations table
    op.create_table(
        'translations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('language_code', sa.String(5), nullable=False),
        sa.Column('translation_key', sa.String(255), nullable=False),
        sa.Column('translated_text', sa.Text(), nullable=False),
        sa.Column('last_updated', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(['language_code'], ['languages.code'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['translation_key'], ['translation_keys.key'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('language_code', 'translation_key', name='uq_language_key')
    )
    op.create_index('ix_translations_language', 'translations', ['language_code'])
    op.create_index('ix_translations_key', 'translations', ['translation_key'])
    
    # 4. Add language preferences to users and usergroups
    op.add_column('users', sa.Column('preferred_language', sa.String(5), nullable=True))
    op.add_column('user_groups', sa.Column('default_language', sa.String(5), nullable=False, server_default='en'))
    
    # 5. Seed initial languages
    languages_table = table('languages',
        column('code', sa.String),
        column('name', sa.String),
        column('is_active', sa.Boolean)
    )
    
    op.bulk_insert(languages_table, [
        {'code': 'en', 'name': 'English', 'is_active': True},
        {'code': 'fr', 'name': 'Français', 'is_active': True}
    ])
    
    # 6. Seed common translation keys (English baseline)
    translation_keys_table = table('translation_keys',
        column('key', sa.String),
        column('category', sa.String),
        column('context', sa.String),
        column('default_text', sa.String)
    )
    
    initial_keys = [
        # Common actions
        {'key': 'common.save', 'category': 'common', 'context': 'Save button', 'default_text': 'Save'},
        {'key': 'common.cancel', 'category': 'common', 'context': 'Cancel button', 'default_text': 'Cancel'},
        {'key': 'common.delete', 'category': 'common', 'context': 'Delete button', 'default_text': 'Delete'},
        {'key': 'common.edit', 'category': 'common', 'context': 'Edit button', 'default_text': 'Edit'},
        {'key': 'common.add', 'category': 'common', 'context': 'Add button', 'default_text': 'Add'},
        {'key': 'common.back', 'category': 'common', 'context': 'Back button', 'default_text': 'Back'},
        {'key': 'common.close', 'category': 'common', 'context': 'Close button', 'default_text': 'Close'},
        {'key': 'common.confirm', 'category': 'common', 'context': 'Confirm button', 'default_text': 'Confirm'},
        {'key': 'common.search', 'category': 'common', 'context': 'Search input placeholder', 'default_text': 'Search'},
        {'key': 'common.loading', 'category': 'common', 'context': 'Loading message', 'default_text': 'Loading...'},
        {'key': 'common.error', 'category': 'common', 'context': 'Generic error', 'default_text': 'An error occurred'},
        {'key': 'common.success', 'category': 'common', 'context': 'Generic success', 'default_text': 'Success'},
        {'key': 'common.yes', 'category': 'common', 'context': 'Yes option', 'default_text': 'Yes'},
        {'key': 'common.no', 'category': 'common', 'context': 'No option', 'default_text': 'No'},
        
        # Dashboard
        {'key': 'dashboard.welcome', 'category': 'dashboard', 'context': 'Dashboard welcome header', 'default_text': 'Welcome to your dashboard'},
        {'key': 'dashboard.title', 'category': 'dashboard', 'context': 'Dashboard page title', 'default_text': 'Dashboard'},
        {'key': 'dashboard.overview', 'category': 'dashboard', 'context': 'Overview section', 'default_text': 'Overview'},
        
        # Fleet management
        {'key': 'fleet.title', 'category': 'fleet', 'context': 'Fleet page title', 'default_text': 'Fleet'},
        {'key': 'fleet.vehicles', 'category': 'fleet', 'context': 'Vehicles list', 'default_text': 'Vehicles'},
        {'key': 'fleet.add_vehicle', 'category': 'fleet', 'context': 'Add vehicle button', 'default_text': 'Add Vehicle'},
        {'key': 'fleet.vehicle_name', 'category': 'fleet', 'context': 'Vehicle name field', 'default_text': 'Vehicle Name'},
        {'key': 'fleet.license_plate', 'category': 'fleet', 'context': 'License plate field', 'default_text': 'License Plate'},
        
        # Geofences
        {'key': 'geofences.title', 'category': 'geofences', 'context': 'Geofences page title', 'default_text': 'Geofences'},
        {'key': 'geofences.add', 'category': 'geofences', 'context': 'Add geofence button', 'default_text': 'Add Geofence'},
        {'key': 'geofences.name', 'category': 'geofences', 'context': 'Geofence name field', 'default_text': 'Geofence Name'},
        {'key': 'geofences.radius', 'category': 'geofences', 'context': 'Geofence radius field', 'default_text': 'Radius (meters)'},
        
        # Trips
        {'key': 'trips.title', 'category': 'trips', 'context': 'Trips page title', 'default_text': 'Trips'},
        {'key': 'trips.history', 'category': 'trips', 'context': 'Trip history', 'default_text': 'Trip History'},
        {'key': 'trips.start_time', 'category': 'trips', 'context': 'Trip start time', 'default_text': 'Start Time'},
        {'key': 'trips.end_time', 'category': 'trips', 'context': 'Trip end time', 'default_text': 'End Time'},
        {'key': 'trips.distance', 'category': 'trips', 'context': 'Trip distance', 'default_text': 'Distance'},
        {'key': 'trips.duration', 'category': 'trips', 'context': 'Trip duration', 'default_text': 'Duration'},
        
        # Alerts
        {'key': 'alerts.title', 'category': 'alerts', 'context': 'Alerts page title', 'default_text': 'Alerts'},
        {'key': 'alerts.geofence_entry', 'category': 'alerts', 'context': 'Geofence entry alert', 'default_text': 'Entered geofence'},
        {'key': 'alerts.geofence_exit', 'category': 'alerts', 'context': 'Geofence exit alert', 'default_text': 'Exited geofence'},
        {'key': 'alerts.speeding', 'category': 'alerts', 'context': 'Speeding alert', 'default_text': 'Speeding detected'},
        
        # Settings
        {'key': 'settings.title', 'category': 'settings', 'context': 'Settings page title', 'default_text': 'Settings'},
        {'key': 'settings.language', 'category': 'settings', 'context': 'Language setting', 'default_text': 'Language'},
        {'key': 'settings.profile', 'category': 'settings', 'context': 'Profile settings', 'default_text': 'Profile'},
        {'key': 'settings.notifications', 'category': 'settings', 'context': 'Notification settings', 'default_text': 'Notifications'},
        
        # Auth
        {'key': 'auth.login', 'category': 'auth', 'context': 'Login button', 'default_text': 'Login'},
        {'key': 'auth.logout', 'category': 'auth', 'context': 'Logout button', 'default_text': 'Logout'},
        {'key': 'auth.email', 'category': 'auth', 'context': 'Email field', 'default_text': 'Email'},
        {'key': 'auth.password', 'category': 'auth', 'context': 'Password field', 'default_text': 'Password'},
        {'key': 'auth.forgot_password', 'category': 'auth', 'context': 'Forgot password link', 'default_text': 'Forgot Password?'},
    ]
    
    op.bulk_insert(translation_keys_table, initial_keys)


def downgrade():
    # Remove language columns
    op.drop_column('user_groups', 'default_language')
    op.drop_column('users', 'preferred_language')
    
    # Drop tables in reverse order (respect foreign keys)
    op.drop_index('ix_translations_key', table_name='translations')
    op.drop_index('ix_translations_language', table_name='translations')
    op.drop_table('translations')
    
    op.drop_index('ix_translation_keys_category', table_name='translation_keys')
    op.drop_table('translation_keys')
    
    op.drop_table('languages')
