"""add critical service alert subscriptions

Revision ID: 046_critical_alert_subs
Revises: 045_nullable_tracker_id
Create Date: 2026-06-07 16:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects import postgresql
import uuid


# revision identifiers, used by Alembic.
revision = '046_critical_alert_subs'
down_revision = '045_nullable_tracker_id'
branch_labels = None
depends_on = None


critical_service_category = sa.Enum(
    'poller_core',
    'tracksolid',
    'mzone',
    'pareto_bridge',
    'email_delivery',
    'database_errors',
    'container_health',
    name='critical_service_category',
)

# Use a column enum object that does NOT auto-create the PostgreSQL type.
# We create the type explicitly once (with IF NOT EXISTS semantics) below.
critical_service_category_col = postgresql.ENUM(
    'poller_core',
    'tracksolid',
    'mzone',
    'pareto_bridge',
    'email_delivery',
    'database_errors',
    'container_health',
    name='critical_service_category',
    create_type=False,
)


def upgrade() -> None:
    # Guarded CREATE TYPE so this migration is idempotent even if the enum
    # already exists from previous partial runs or metadata side effects.
    op.execute(
        """
        DO $$
        BEGIN
            CREATE TYPE critical_service_category AS ENUM (
                'poller_core',
                'tracksolid',
                'mzone',
                'pareto_bridge',
                'email_delivery',
                'database_errors',
                'container_health'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END
        $$;
        """
    )

    op.create_table(
        'critical_service_alert_subscriptions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('category', critical_service_category_col, nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('failure_threshold', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('window_minutes', sa.Integer(), nullable=False, server_default='15'),
        sa.Column('cooldown_minutes', sa.Integer(), nullable=False, server_default='60'),
        sa.Column('recipient_emails', sa.JSON(), nullable=True),
        sa.Column('last_alert_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        'ix_critical_service_alert_subscriptions_category',
        'critical_service_alert_subscriptions',
        ['category'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        'ix_critical_service_alert_subscriptions_category',
        table_name='critical_service_alert_subscriptions',
    )
    op.drop_table('critical_service_alert_subscriptions')

    bind = op.get_bind()
    critical_service_category.drop(bind, checkfirst=True)
