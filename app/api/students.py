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

@router.get("", response_model=List[StudentResponse])
@router.get("/", response_model=List[StudentResponse], include_in_schema=False)
async def list_students(
    route_id: Optional[str] = Query(None, description="Filter by route ID"),
    parent_id: Optional[str] = Query(None, description="Filter by parent profile ID"),
    grade: Optional[str] = Query(None, description="Filter by grade"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100, description="Pagination limit (max 100)"),
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Retrieve all students with optional filtering and pagination.
    Resolves effective route for today (Asia/Kolkata) so parents track the approved route.
    """
    query = select(Student)
    if current_user.role == "parent":
        query = query.where(Student.parent_id == str(current_user.id))
    elif current_user.role == "teacher":
        from app.services.attendance_service import get_teacher_route_ids
        t_routes = await get_teacher_route_ids(db, str(current_user.id))
        if not t_routes:
            return []
        query = query.where(Student.route_id.in_(t_routes))
    elif current_user.role == "driver":
        from app.services.attendance_service import get_driver_accessible_route_ids
        d_routes = await get_driver_accessible_route_ids(db, str(current_user.id))
        if not d_routes:
            return []
        query = query.where(Student.route_id.in_(d_routes))
    elif parent_id:
        query = query.where(Student.parent_id == parent_id)
    if route_id:
        query = query.where(Student.route_id == route_id)
    if grade:
        query = query.where(Student.grade == grade)

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    students = result.scalars().all()

    from app.services.attendance_service import get_effective_route_and_bus_for_student, get_kolkata_today
    today = get_kolkata_today()
    response_students = []
    for s in students:
        eff_route, _ = await get_effective_route_and_bus_for_student(db, str(s.id), today)
        s_dict = {
            "id": str(s.id),
            "first_name": s.first_name,
            "last_name": s.last_name,
            "grade": s.grade,
            "parent_id": str(s.parent_id) if s.parent_id else None,
            "route_id": eff_route or (str(s.route_id) if s.route_id else None),
            "pickup_stop": s.pickup_stop,
            "dropoff_stop": s.dropoff_stop,
            "qr_code_id": s.qr_code_id,
            "created_at": s.created_at,
        }
        response_students.append(StudentResponse.model_validate(s_dict))
    return response_students

@router.post("", response_model=StudentResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=StudentResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_student(
    student_in: StudentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Create a new student record.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage students."
        )

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
    if current_user.role == "parent" and (not student.parent_id or str(student.parent_id) != str(current_user.id)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this student record"
        )
    elif current_user.role == "teacher":
        from app.services.attendance_service import is_student_assigned_to_teacher
        is_assigned = await is_student_assigned_to_teacher(db, str(student.id), str(current_user.id))
        if not is_assigned:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: student not on your route."
            )
    elif current_user.role == "driver":
        from app.services.attendance_service import get_driver_accessible_route_ids
        d_routes = await get_driver_accessible_route_ids(db, str(current_user.id))
        if not student.route_id or str(student.route_id) not in d_routes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: student not on your route."
            )
    from app.services.attendance_service import get_effective_route_and_bus_for_student, get_kolkata_today
    eff_route, _ = await get_effective_route_and_bus_for_student(db, str(student.id), get_kolkata_today())
    s_dict = {
        "id": str(student.id),
        "first_name": student.first_name,
        "last_name": student.last_name,
        "grade": student.grade,
        "parent_id": str(student.parent_id) if student.parent_id else None,
        "route_id": eff_route or (str(student.route_id) if student.route_id else None),
        "pickup_stop": student.pickup_stop,
        "dropoff_stop": student.dropoff_stop,
        "qr_code_id": student.qr_code_id,
        "created_at": student.created_at,
    }
    return StudentResponse.model_validate(s_dict)

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
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage students."
        )

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
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage students."
        )

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
