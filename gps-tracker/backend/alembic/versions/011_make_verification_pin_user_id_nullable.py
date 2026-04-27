"""Make verification_pins.user_id nullable (user created only at /register)

Revision ID: 011
Revises: 010
Create Date: 2025-01-01

Previously, a User record was created at the /send-pin step, so user_id was
immediately available on the VerificationPIN row. The registration flow has been
corrected so that:
  1. /send-pin  — creates VerificationPIN only (user_id = NULL)
  2. /verify-pin — marks PIN as used, returns success (no token, no user row)
  3. /register   — creates the User row with all details and returns the JWT

This migration drops the NOT NULL constraint from verification_pins.user_id.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'verification_pins',
        'user_id',
        existing_type=sa.String(36),  # UUID stored as String(36) on SQLite; no-op label for PG
        nullable=True,
    )


def downgrade():
    # WARNING: This will fail if any rows have user_id = NULL.
    # Clean up orphan rows first before running downgrade.
    op.alter_column(
        'verification_pins',
        'user_id',
        existing_type=sa.String(36),
        nullable=False,
    )
