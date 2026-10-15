"""add_attendance_table

Revision ID: 8e29d71c4f10
Revises: 438934aedc4e
Create Date: 2026-09-09 02:44:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8e29d71c4f10'
down_revision: Union[str, Sequence[str], None] = '438934aedc4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'attendance',
        sa.Column('id', sa.UUID(as_uuid=False), primary_key=True),
        sa.Column('student_id', sa.UUID(as_uuid=False), sa.ForeignKey('students.id', ondelete='CASCADE'), nullable=False),
        sa.Column('bus_id', sa.UUID(as_uuid=False), sa.ForeignKey('buses.id', ondelete='SET NULL'), nullable=True),
        sa.Column('route_id', sa.UUID(as_uuid=False), sa.ForeignKey('routes.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('action_type', sa.String(50), nullable=False),
        sa.Column('scanned_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('scanned_by', sa.UUID(as_uuid=False), sa.ForeignKey('profiles.id', ondelete='SET NULL'), nullable=True),
    )
    op.create_index('idx_attendance_student_scanned', 'attendance', ['student_id', 'scanned_at'])


def downgrade() -> None:
    op.drop_index('idx_attendance_student_scanned', table_name='attendance')
    op.drop_table('attendance')
