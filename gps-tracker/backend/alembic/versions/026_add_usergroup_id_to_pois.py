"""Add usergroup_id to pois and make user_id nullable

Revision ID: 026
Revises: 025
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = '026'
down_revision = '025'
branch_labels = None
depends_on = None


def upgrade():
    # Make user_id nullable on pois (portal-created POIs have no mobile user)
    # ALTER COLUMN is idempotent when already nullable
    op.execute("ALTER TABLE pois ALTER COLUMN user_id DROP NOT NULL")

    # Add usergroup_id — IF NOT EXISTS guards against partial re-runs
    op.execute("ALTER TABLE pois ADD COLUMN IF NOT EXISTS usergroup_id VARCHAR(36)")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_pois_usergroup_id'
            ) THEN
                ALTER TABLE pois ADD CONSTRAINT fk_pois_usergroup_id
                    FOREIGN KEY (usergroup_id) REFERENCES user_groups(id) ON DELETE CASCADE;
            END IF;
        END $$
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_pois_usergroup_id ON pois (usergroup_id)")


def downgrade():
    op.drop_index('ix_pois_usergroup_id', table_name='pois')
    op.drop_constraint('fk_pois_usergroup_id', 'pois', type_='foreignkey')
    op.drop_column('pois', 'usergroup_id')
    op.alter_column('pois', 'user_id', nullable=False)
