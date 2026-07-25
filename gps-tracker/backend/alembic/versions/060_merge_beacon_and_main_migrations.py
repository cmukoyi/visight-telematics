"""Merge beacon (049_hive_persistence) and main (v2111_d1_late_arrivals) migration heads

Revision ID: 060_merge_heads
Revises: 049_hive_persistence, v2111_d1_late_arrivals
Create Date: 2026-07-25

This merge migration resolves the diverged migration chains:
- prod/beacon branch: 048 → 049_hive_persistence
- main branch: 048 → 049_i18n → 050 → ... → v2111_d1_late_arrivals

After this merge, both histories are unified and future migrations can proceed linearly.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '060_merge_heads'
down_revision = ('049_hive_persistence', 'v2111_d1_late_arrivals')
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge migration - no schema changes needed.
    
    Both branches have been running in production:
    - Beacon has Hive tables (from 049_hive_persistence)
    - PinPlot has i18n tables, Trip Engine tables (from 049+ on main)
    
    This migration simply acknowledges both exist.
    """
    pass


def downgrade() -> None:
    """No downgrade needed for merge migration."""
    pass
