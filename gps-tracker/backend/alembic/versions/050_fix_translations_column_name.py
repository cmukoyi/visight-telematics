"""fix translations column name

Revision ID: 050_fix_translations_column_name
Revises: 049_add_i18n_tables
Create Date: 2026-06-18 20:45:00.000000

This migration fixes the column name in the translations table.
Migration 049 was deployed with the buggy code that used 'translation_key',
but the correct column name should be 'key' to avoid conflicts with the
SQLAlchemy relationship of the same name.

This migration can be safely applied even if the column is already named 'key'.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '050_fix_translations_column_name'
down_revision = '049_add_i18n_tables'
branch_labels = None
depends_on = None


def upgrade():
    # Check if column 'translation_key' exists and rename it to 'key'
    # This is idempotent - if 'key' already exists, this does nothing
    conn = op.get_bind()
    
    # Check if 'translation_key' column exists
    result = conn.execute(sa.text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'translations' 
        AND column_name = 'translation_key'
    """))
    
    has_old_column = result.fetchone() is not None
    
    if has_old_column:
        # Drop existing constraints and indexes that reference the old column name
        op.drop_constraint('uq_language_key', 'translations', type_='unique')
        op.drop_constraint('translations_translation_key_fkey', 'translations', type_='foreignkey')
        op.drop_index('ix_translations_key', table_name='translations')
        
        # Rename the column
        op.alter_column('translations', 'translation_key', new_column_name='key')
        
        # Recreate constraints and indexes with the new column name
        op.create_index('ix_translations_key', 'translations', ['key'])
        op.create_unique_constraint('uq_language_key', 'translations', ['language_code', 'key'])
        op.create_foreign_key(
            'translations_key_fkey', 
            'translations', 
            'translation_keys',
            ['key'], 
            ['key'],
            ondelete='CASCADE'
        )


def downgrade():
    # Reverse the changes - rename 'key' back to 'translation_key'
    conn = op.get_bind()
    
    # Check if 'key' column exists
    result = conn.execute(sa.text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'translations' 
        AND column_name = 'key'
    """))
    
    has_new_column = result.fetchone() is not None
    
    if has_new_column:
        # Drop constraints and indexes
        op.drop_constraint('uq_language_key', 'translations', type_='unique')
        op.drop_constraint('translations_key_fkey', 'translations', type_='foreignkey')
        op.drop_index('ix_translations_key', table_name='translations')
        
        # Rename the column back
        op.alter_column('translations', 'key', new_column_name='translation_key')
        
        # Recreate constraints and indexes with the old column name
        op.create_index('ix_translations_key', 'translations', ['translation_key'])
        op.create_unique_constraint('uq_language_key', 'translations', ['language_code', 'translation_key'])
        op.create_foreign_key(
            'translations_translation_key_fkey',
            'translations',
            'translation_keys',
            ['translation_key'],
            ['key'],
            ondelete='CASCADE'
        )
