"""Set role='system_admin' for all portal_users where is_group_admin=True.

These are the initial admin accounts created automatically when a UserGroup
is provisioned. They are now distinguished from regular Admin users by the
'system_admin' role, which is displayed as "Built-in System Admin" in the
customer portal and cannot be edited or deactivated via the portal UI.

Revision ID: 029
Revises: 028
Create Date: 2026-04-29
"""
from alembic import op

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        UPDATE portal_users
        SET    role = 'system_admin'
        WHERE  is_group_admin = TRUE
          AND  role = 'admin'
        """
    )


def downgrade():
    op.execute(
        """
        UPDATE portal_users
        SET    role = 'admin'
        WHERE  is_group_admin = TRUE
          AND  role = 'system_admin'
        """
    )
