"""add_route_change_requests

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-15 22:35:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'route_change_requests',
        sa.Column('id', sa.UUID(as_uuid=False), primary_key=True),
        sa.Column('student_id', sa.UUID(as_uuid=False), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('requested_by', sa.UUID(as_uuid=False), sa.ForeignKey('profiles.id', ondelete='CASCADE'), nullable=False),
        sa.Column('target_route_id', sa.UUID(as_uuid=False), sa.ForeignKey('routes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('target_bus_id', sa.UUID(as_uuid=False), sa.ForeignKey('buses.id', ondelete='SET NULL'), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('reviewed_by', sa.UUID(as_uuid=False), sa.ForeignKey('profiles.id', ondelete='SET NULL'), nullable=True),
        sa.Column('review_notes', sa.String(500), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'cancelled')", name="check_route_change_status")
    )
    op.create_index('ix_route_change_requests_student_id', 'route_change_requests', ['student_id'])
    op.create_index('ix_route_change_requests_requested_by', 'route_change_requests', ['requested_by'])
    op.create_index('ix_route_change_requests_target_route_id', 'route_change_requests', ['target_route_id'])
    op.create_index('ix_route_change_requests_start_date', 'route_change_requests', ['start_date'])
    op.create_index('ix_route_change_requests_end_date', 'route_change_requests', ['end_date'])


def downgrade() -> None:
    op.drop_index('ix_route_change_requests_end_date', table_name='route_change_requests')
    op.drop_index('ix_route_change_requests_start_date', table_name='route_change_requests')
    op.drop_index('ix_route_change_requests_target_route_id', table_name='route_change_requests')
    op.drop_index('ix_route_change_requests_requested_by', table_name='route_change_requests')
    op.drop_index('ix_route_change_requests_student_id', table_name='route_change_requests')
    op.drop_table('route_change_requests')
