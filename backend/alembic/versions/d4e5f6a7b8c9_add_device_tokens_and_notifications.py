"""add_device_tokens_and_notifications

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-15 22:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create device_tokens table
    op.create_table(
        'device_tokens',
        sa.Column('id', sa.UUID(as_uuid=False), primary_key=True),
        sa.Column('user_id', sa.UUID(as_uuid=False), sa.ForeignKey('profiles.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token', sa.String(500), nullable=False, unique=True),
        sa.Column('platform', sa.String(50), nullable=False, server_default='android'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_device_tokens_user_id', 'device_tokens', ['user_id'])
    op.create_index('ix_device_tokens_token', 'device_tokens', ['token'])

    # 2. Create notification_logs table
    op.create_table(
        'notification_logs',
        sa.Column('id', sa.UUID(as_uuid=False), primary_key=True),
        sa.Column('user_id', sa.UUID(as_uuid=False), sa.ForeignKey('profiles.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('data_payload', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='sent'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_notification_logs_user_id', 'notification_logs', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_notification_logs_user_id', table_name='notification_logs')
    op.drop_table('notification_logs')
    op.drop_index('ix_device_tokens_token', table_name='device_tokens')
    op.drop_index('ix_device_tokens_user_id', table_name='device_tokens')
    op.drop_table('device_tokens')
