"""ensure_profiles_role_check_includes_teacher

Revision ID: f1a2b3c4d5e6
Revises: e5f6a7b8c9d0
Create Date: 2026-10-17 11:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == 'postgresql':
        # Dynamically discover any existing check constraints mentioning role on public.profiles
        sql = sa.text("""
            SELECT c.conname, pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_namespace n ON n.oid = c.connamespace
            JOIN pg_class cl ON cl.oid = c.conrelid
            WHERE n.nspname = 'public' 
              AND cl.relname = 'profiles' 
              AND c.contype = 'c' 
              AND pg_get_constraintdef(c.oid) LIKE '%role%'
        """)
        rows = conn.execute(sql).fetchall()

        already_valid = False
        for conname, condef in rows:
            condef_lower = condef.lower()
            if (
                "teacher" in condef_lower
                and "admin" in condef_lower
                and "parent" in condef_lower
                and "driver" in condef_lower
                and "staff" not in condef_lower
            ):
                already_valid = True
            else:
                op.drop_constraint(conname, 'profiles', type_='check')

        if not already_valid:
            op.create_check_constraint(
                'profiles_role_check',
                'profiles',
                sa.text("role IN ('admin', 'teacher', 'parent', 'driver')")
            )
    else:
        # SQLite or mock engine fallback
        pass


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == 'postgresql':
        sql = sa.text("""
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_namespace n ON n.oid = c.connamespace
            JOIN pg_class cl ON cl.oid = c.conrelid
            WHERE n.nspname = 'public' 
              AND cl.relname = 'profiles' 
              AND c.contype = 'c' 
              AND pg_get_constraintdef(c.oid) LIKE '%role%'
        """)
        rows = conn.execute(sql).fetchall()
        for conname, in rows:
            op.drop_constraint(conname, 'profiles', type_='check')
        op.create_check_constraint(
            'profiles_role_check',
            'profiles',
            sa.text("role IN ('admin', 'staff', 'parent', 'driver')")
        )
