"""add_teacher_to_routes_and_attendance_date

Revision ID: c3d4e5f6a7b8
Revises: 8e29d71c4f10
Create Date: 2026-10-15 21:58:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = '8e29d71c4f10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    context = op.get_context()
    dialect_name = context.dialect.name if context.dialect else 'postgresql'

    # 1. Add teacher_id to routes
    op.add_column(
        'routes',
        sa.Column(
            'teacher_id',
            sa.UUID(as_uuid=False),
            sa.ForeignKey('profiles.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )

    # 2. Add attendance_date to attendance (nullable initially for backfill)
    op.add_column(
        'attendance',
        sa.Column('attendance_date', sa.Date(), nullable=True),
    )

    # 3. Backfill attendance_date from scanned_at in Asia/Kolkata timezone
    if dialect_name == 'postgresql':
        op.execute(
            sa.text(
                "UPDATE attendance "
                "SET attendance_date = (scanned_at AT TIME ZONE 'Asia/Kolkata')::date "
                "WHERE attendance_date IS NULL"
            )
        )
    else:
        op.execute(
            sa.text(
                "UPDATE attendance "
                "SET attendance_date = date(scanned_at) "
                "WHERE attendance_date IS NULL"
            )
        )

    # 4. Handle duplicates safely before adding UNIQUE constraint
    # Keep the latest record by scanned_at, id
    op.execute(
        sa.text(
            """
            DELETE FROM attendance
            WHERE id NOT IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY student_id, attendance_date, action_type
                        ORDER BY scanned_at DESC, id DESC
                    ) as rnum
                    FROM attendance
                ) t WHERE t.rnum = 1
            )
            """
        )
    )

    # 5. Make attendance_date non-nullable
    op.alter_column('attendance', 'attendance_date', nullable=False)

    # 6. Add UNIQUE constraint on (student_id, attendance_date, action_type)
    op.create_unique_constraint(
        'uq_attendance_student_date_action',
        'attendance',
        ['student_id', 'attendance_date', 'action_type'],
    )

    # 7. Drop existing status CHECK constraint BEFORE normalizing statuses to 'present'
    # Dynamically queries pg_constraint to robustly drop the constraint regardless of exact name
    if dialect_name == 'postgresql':
        op.execute(
            sa.text(
                """
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_class cl ON cl.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = cl.relnamespace
        WHERE n.nspname = 'public'
          AND cl.relname = 'attendance'
          AND c.contype = 'c'
          AND pg_get_constraintdef(c.oid) LIKE '%status%'
    ) LOOP
        EXECUTE 'ALTER TABLE attendance DROP CONSTRAINT ' || quote_ident(r.conname);
    END LOOP;
END $$
                """
            )
        )

    # 8. Normalize legacy statuses to 'present'
    op.execute(
        sa.text(
            "UPDATE attendance "
            "SET status = 'present' "
            "WHERE status IN ('boarded', 'dropped', 'disembarked')"
        )
    )

    # 9. Add new CHECK constraint enforcing 'present' or 'absent'
    if dialect_name == 'postgresql':
        op.execute(
            sa.text(
                "ALTER TABLE attendance ADD CONSTRAINT attendance_status_check CHECK (status IN ('present', 'absent'))"
            )
        )


def downgrade() -> None:
    context = op.get_context()
    dialect_name = context.dialect.name if context.dialect else 'postgresql'

    # 1. Robustly drop the current status check constraint
    if dialect_name == 'postgresql':
        op.execute(
            sa.text(
                """
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_class cl ON cl.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = cl.relnamespace
        WHERE n.nspname = 'public'
          AND cl.relname = 'attendance'
          AND c.contype = 'c'
          AND pg_get_constraintdef(c.oid) LIKE '%status%'
    ) LOOP
        EXECUTE 'ALTER TABLE attendance DROP CONSTRAINT ' || quote_ident(r.conname);
    END LOOP;
END $$
                """
            )
        )
        # Re-add original check constraint
        op.execute(
            sa.text(
                "ALTER TABLE attendance ADD CONSTRAINT attendance_status_check CHECK (status IN ('boarded', 'disembarked', 'absent'))"
            )
        )

    # 2. Drop unique constraint
    op.drop_constraint('uq_attendance_student_date_action', 'attendance', type_='unique')

    # 3. Drop attendance_date column
    op.drop_column('attendance', 'attendance_date')

    # 4. Drop teacher_id column from routes
    op.drop_column('routes', 'teacher_id')
