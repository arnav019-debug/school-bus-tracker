"""rename_staff_to_teacher

Revision ID: 438934aedc4e
Revises: f749d66e2a2a
Create Date: 2026-08-09 23:20:06.926837

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '438934aedc4e'
down_revision: Union[str, Sequence[str], None] = 'f749d66e2a2a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def discover_and_verify_role_constraint(conn, is_upgrade=True):
    # Dynamically find constraint name and definition
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
    result = conn.execute(sql)
    rows = result.fetchall()
    
    if len(rows) == 0:
        raise Exception("Aborting migration: No check constraints found on profiles table mentioning 'role'.")
    if len(rows) > 1:
        names = [r[0] for r in rows]
        raise Exception(f"Aborting migration: Expected exactly one check constraint mentioning 'role', but found multiple: {names}")
        
    conname, condef = rows[0]
    print(f"Discovered constraint: Name={conname}, Definition={condef}")
    
    # Normalize definition to lowercase for safe matching
    condef_lower = condef.lower()
    
    if is_upgrade:
        required_words = ["admin", "staff", "parent", "driver"]
        for word in required_words:
            if word not in condef_lower:
                raise Exception(f"Aborting migration: Discovered constraint '{conname}' does not match expected definition. Missing '{word}' in: {condef}")
        if "teacher" in condef_lower:
            raise Exception(f"Aborting migration: Discovered constraint '{conname}' already includes 'teacher' in: {condef}")
    else:
        required_words = ["admin", "teacher", "parent", "driver"]
        for word in required_words:
            if word not in condef_lower:
                raise Exception(f"Aborting migration: Discovered constraint '{conname}' does not match expected definition. Missing '{word}' in: {condef}")
        if "staff" in condef_lower:
            raise Exception(f"Aborting migration: Discovered constraint '{conname}' already includes 'staff' in: {condef}")
            
    return conname

def upgrade() -> None:
    conn = op.get_bind()
    
    if conn.dialect.name == 'postgresql':
        # 1. Discover and verify constraints
        constraint_name = discover_and_verify_role_constraint(conn, is_upgrade=True)
        
        # 2. Check for unexpected role values
        result = conn.execute(sa.text("SELECT DISTINCT role FROM public.profiles"))
        existing_roles = {row[0] for row in result.fetchall()}
        allowed_roles = {'admin', 'staff', 'parent', 'driver'}
        unexpected = existing_roles - allowed_roles
        if unexpected:
            raise Exception(f"Aborting migration. Found unexpected roles in database: {unexpected}")

        # 3. Drop constraint
        op.drop_constraint(constraint_name, 'profiles', type_='check')
            
        # 4. Update data inside transaction
        conn.execute(sa.text("UPDATE public.profiles SET role = 'teacher' WHERE role = 'staff'"))
        
        # 5. Add new constraint
        op.create_check_constraint(
            'profiles_role_check',
            'profiles',
            sa.text("role IN ('admin', 'teacher', 'parent', 'driver')")
        )
        
        # 6. Verify no staff remaining
        res = conn.execute(sa.text("SELECT COUNT(*) FROM public.profiles WHERE role = 'staff'"))
        count = res.scalar()
        if count > 0:
            raise Exception("Validation failed: 'staff' roles still exist in profiles table.")
    else:
        # For SQLite (or other testing engines), just run updates and check
        conn.execute(sa.text("UPDATE profiles SET role = 'teacher' WHERE role = 'staff'"))
        res = conn.execute(sa.text("SELECT COUNT(*) FROM profiles WHERE role = 'staff'"))
        count = res.scalar()
        if count > 0:
            raise Exception("Validation failed: 'staff' roles still exist in profiles table.")

def downgrade() -> None:
    conn = op.get_bind()
    
    if conn.dialect.name == 'postgresql':
        constraint_name = discover_and_verify_role_constraint(conn, is_upgrade=False)
        
        op.drop_constraint(constraint_name, 'profiles', type_='check')
            
        conn.execute(sa.text("UPDATE public.profiles SET role = 'staff' WHERE role = 'teacher'"))
        
        op.create_check_constraint(
            'profiles_role_check',
            'profiles',
            sa.text("role IN ('admin', 'staff', 'parent', 'driver')")
        )
        
        res = conn.execute(sa.text("SELECT COUNT(*) FROM public.profiles WHERE role = 'teacher'"))
        count = res.scalar()
        if count > 0:
            raise Exception("Validation failed: 'teacher' roles still exist in profiles table.")
    else:
        conn.execute(sa.text("UPDATE profiles SET role = 'staff' WHERE role = 'teacher'"))
        res = conn.execute(sa.text("SELECT COUNT(*) FROM profiles WHERE role = 'teacher'"))
        count = res.scalar()
        if count > 0:
            raise Exception("Validation failed: 'teacher' roles still exist in profiles table.")
