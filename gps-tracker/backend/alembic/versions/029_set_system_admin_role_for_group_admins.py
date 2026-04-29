"""Set role='system_admin' for portal_users created at UserGroup creation.

The initial admin account created when a UserGroup is provisioned has
is_group_admin=TRUE. This is the ONLY place in the codebase that sets
is_group_admin=True (routes_admin.py create_usergroup), so the condition
is precise — it does NOT affect regular Admin portal users added later
(those always have is_group_admin=FALSE regardless of their role).

These built-in accounts are now protected: they display as "Built-in System
Admin" in the customer portal and cannot be modified or deactivated via
the portal PATCH /users/{id} endpoint.

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
