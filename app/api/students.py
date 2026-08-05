from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.student import Student
from app.models.profile import Profile
from app.schemas.student import StudentCreate, StudentUpdate, StudentResponse
from app.api.deps import get_current_user

router = APIRouter()

@router.get("/", response_model=List[StudentResponse])
async def list_students(
    route_id: Optional[str] = Query(None, description="Filter by route ID"),
    parent_id: Optional[str] = Query(None, description="Filter by parent profile ID"),
    grade: Optional[str] = Query(None, description="Filter by grade"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Retrieve all students with optional filtering and pagination.
    """
    query = select(Student)
    if route_id:
        query = query.where(Student.route_id == route_id)
    if parent_id:
        query = query.where(Student.parent_id == parent_id)
    if grade:
        query = query.where(Student.grade == grade)

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    students = result.scalars().all()
    return students

@router.post("/", response_model=StudentResponse, status_code=status.HTTP_201_CREATED)
async def create_student(
    student_in: StudentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Create a new student record.
    """
    student_data = student_in.model_dump()
    if not student_data.get("qr_code_id"):
        student_data.pop("qr_code_id", None)

    student = Student(**student_data)
    db.add(student)
    await db.commit()
    await db.refresh(student)
    return student

@router.get("/{student_id}", response_model=StudentResponse)
async def get_student(
    student_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Get a specific student by ID.
    """
    result = await db.execute(select(Student).where(Student.id == student_id))
    student = result.scalars().first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found"
        )
    return student

@router.put("/{student_id}", response_model=StudentResponse)
async def update_student(
    student_id: str,
    student_in: StudentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Update a student record.
    """
    result = await db.execute(select(Student).where(Student.id == student_id))
    student = result.scalars().first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found"
        )

    update_data = student_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(student, field, value)

    await db.commit()
    await db.refresh(student)
    return student

@router.delete("/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student(
    student_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Delete a student record.
    """
    result = await db.execute(select(Student).where(Student.id == student_id))
    student = result.scalars().first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student not found"
        )

    await db.delete(student)
    await db.commit()
    return None
