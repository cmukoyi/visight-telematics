"""Add per-user temperature alert preference."""
from alembic import op
import sqlalchemy as sa

revision = "temperature_alert_preferences"
down_revision = "link_portal_flutter_users"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("portal_users")}
    if "notify_temperature" not in columns:
        op.add_column(
            "portal_users",
            sa.Column("notify_temperature", sa.Boolean(), nullable=False, server_default=sa.true()),
        )


def downgrade():
    op.drop_column("portal_users", "notify_temperature")