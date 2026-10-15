from datetime import datetime, timezone, date, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.database import get_db
from app.models.attendance import Attendance
from app.models.student import Student
from app.models.route import Route
from app.models.bus import Bus
from app.models.driver import Driver
from app.models.profile import Profile
from app.schemas.attendance import (
    AttendanceCreate,
    AttendanceUpdate,
    AttendanceResponse,
    StudentRosterItem,
)
from app.services.attendance_service import (
    get_kolkata_today,
    get_teacher_route_ids,
    is_student_assigned_to_teacher,
    get_students_for_teacher,
    get_students_for_driver,
    get_effective_route_and_bus_for_student,
)
from app.services.notification_service import notify_parent_on_absent
from app.api.deps import get_current_user

router = APIRouter()

@router.get("/roster", response_model=List[StudentRosterItem])
@router.get("/roster/", response_model=List[StudentRosterItem], include_in_schema=False)
async def get_teacher_roster(
    date_val: Optional[date] = Query(None, alias="date", description="Target date (defaults to today in Asia/Kolkata)"),
    action_type: str = Query("pickup", description="Session action type ('pickup' or 'dropoff')"),
    teacher_id: Optional[str] = Query(None, description="Teacher ID (admins only)"),
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Returns the student roster with attendance status for a teacher, driver, or admin on a given date.
    Teachers only see their own assigned bus/route students.
    Drivers see their own bus/route students.
    Admins can view any teacher's roster.
    """
    target_date = date_val or get_kolkata_today()
    clean_action = action_type.strip().lower()
    if clean_action not in ("pickup", "dropoff"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="action_type must be 'pickup' or 'dropoff'"
        )

    if current_user.role == "teacher":
        return await get_students_for_teacher(db, str(current_user.id), target_date, clean_action)
    elif current_user.role == "driver":
        return await get_students_for_driver(db, str(current_user.id), target_date, clean_action)
    elif current_user.role == "admin":
        if not teacher_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="teacher_id query parameter is required for admin role."
            )
        return await get_students_for_teacher(db, str(teacher_id), target_date, clean_action)
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only teachers, drivers, and administrators can view the attendance roster."
        )

@router.post("", response_model=AttendanceResponse)
@router.post("/", response_model=AttendanceResponse, include_in_schema=False)
async def mark_attendance(
    attendance_in: AttendanceCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Mark or upsert attendance for a student on today's date (Asia/Kolkata).
    Idempotent: updates existing entry for (student_id, date, action_type) if present.
    Teachers may only mark attendance for students on their assigned route/bus.
    """
    # 1. Role validation
    if current_user.role not in ("admin", "teacher"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators and assigned teachers can record attendance."
        )

    # 2. Student lookup
    student_res = await db.execute(select(Student).where(Student.id == attendance_in.student_id))
    student = student_res.scalars().first()
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    # 3. Compute server-side attendance date, timestamp, and recorder
    today_ist = get_kolkata_today()
    attendance_date = attendance_in.attendance_date or today_ist

    # Reject future dates
    if attendance_date > today_ist:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Attendance date cannot be in the future (today is {today_ist.isoformat()})."
        )

    # Limit teachers to the last 7 days (admin unrestricted)
    if current_user.role == "teacher":
        cutoff_date = today_ist - timedelta(days=7)
        if attendance_date < cutoff_date:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Teachers can only record attendance for dates within the last 7 days (cutoff: {cutoff_date.isoformat()})."
            )

        is_assigned = await is_student_assigned_to_teacher(
            db, str(student.id), current_user.id, target_date=attendance_date
        )
        if not is_assigned:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to record attendance for this student: student is not on your assigned route on this date."
            )

    # 4. Resolve effective route and bus for attendance_date
    eff_route, eff_bus = await get_effective_route_and_bus_for_student(db, str(student.id), attendance_date)
    route_id = attendance_in.route_id or eff_route
    bus_id = attendance_in.bus_id or eff_bus

    scanned_at = datetime.now(timezone.utc)
    scanned_by = str(current_user.id)

    # 6. Idempotent check: unique on (student_id, attendance_date, action_type)
    existing_res = await db.execute(
        select(Attendance).where(
            Attendance.student_id == student.id,
            Attendance.attendance_date == attendance_date,
            Attendance.action_type == attendance_in.action_type
        )
    )
    existing = existing_res.scalars().first()

    was_absent = (existing.status == "absent") if existing else False

    if existing:
        existing.status = attendance_in.status
        existing.bus_id = bus_id
        existing.route_id = route_id
        existing.scanned_at = scanned_at
        existing.scanned_by = scanned_by
        await db.commit()
        await db.refresh(existing)
        if attendance_in.status == "absent" and not was_absent:
            await notify_parent_on_absent(db, str(student.id), attendance_date, attendance_in.action_type, str(current_user.id))
        response.status_code = status.HTTP_200_OK
        return existing
    else:
        new_attendance = Attendance(
            student_id=str(student.id),
            bus_id=bus_id,
            route_id=route_id,
            attendance_date=attendance_date,
            status=attendance_in.status,
            action_type=attendance_in.action_type,
            scanned_at=scanned_at,
            scanned_by=scanned_by,
        )
        db.add(new_attendance)
        await db.commit()
        await db.refresh(new_attendance)
        if attendance_in.status == "absent":
            await notify_parent_on_absent(db, str(student.id), attendance_date, attendance_in.action_type, str(current_user.id))
        response.status_code = status.HTTP_201_CREATED
        return new_attendance

@router.get("", response_model=List[AttendanceResponse])
@router.get("/", response_model=List[AttendanceResponse], include_in_schema=False)
async def list_attendance(
    student_id: Optional[str] = Query(None, description="Filter by student ID"),
    route_id: Optional[str] = Query(None, description="Filter by route ID"),
    bus_id: Optional[str] = Query(None, description="Filter by bus ID"),
    date_val: Optional[date] = Query(None, alias="date", description="Filter by attendance date (YYYY-MM-DD)"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status ('present' or 'absent')"),
    action_type: Optional[str] = Query(None, description="Filter by action type ('pickup' or 'dropoff')"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100, description="Pagination limit (max 100)"),
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Retrieve attendance records scoped strictly to the requesting user:
    - Parents: only their own children.
    - Teachers: only students on their assigned route/bus.
    - Drivers: only students on their assigned bus.
    - Admins: unrestricted.
    """
    query = select(Attendance)

    # Enforce role-based data scoping
    if current_user.role == "parent":
        children_res = await db.execute(select(Student.id).where(Student.parent_id == str(current_user.id)))
        child_ids = [str(r[0]) for r in children_res.fetchall()]
        if not child_ids:
            return []
        query = query.where(Attendance.student_id.in_(child_ids))

    elif current_user.role == "teacher":
        teacher_routes = await get_teacher_route_ids(db, current_user.id)
        if not teacher_routes:
            return []
        students_res = await db.execute(select(Student.id).where(Student.route_id.in_(teacher_routes)))
        teacher_student_ids = [str(r[0]) for r in students_res.fetchall()]
        if not teacher_student_ids:
            return []
        query = query.where(Attendance.student_id.in_(teacher_student_ids))

    elif current_user.role == "driver":
        driver_res = await db.execute(select(Driver.id).where(Driver.user_id == str(current_user.id)))
        driver = driver_res.scalars().first()
        if not driver:
            return []
        buses_res = await db.execute(select(Bus.id).where(Bus.driver_id == driver.id))
        driver_bus_ids = {str(b[0]) for b in buses_res.fetchall()}
        routes_res = await db.execute(select(Route.id, Route.bus_id).where(Route.driver_id == driver.id))
        driver_route_ids = set()
        for r_id, b_id in routes_res.fetchall():
            driver_route_ids.add(str(r_id))
            if b_id:
                driver_bus_ids.add(str(b_id))
        if not driver_bus_ids and not driver_route_ids:
            return []
        query = query.where(
            or_(
                Attendance.bus_id.in_(list(driver_bus_ids)),
                Attendance.route_id.in_(list(driver_route_ids))
            )
        )

    elif current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Optional filters
    if student_id:
        query = query.where(Attendance.student_id == student_id)
    if route_id:
        query = query.where(Attendance.route_id == route_id)
    if bus_id:
        query = query.where(Attendance.bus_id == bus_id)
    if status_filter:
        clean_status = "present" if status_filter.strip().lower() in ("present", "boarded", "dropped", "disembarked") else status_filter.strip().lower()
        query = query.where(Attendance.status == clean_status)
    if action_type:
        query = query.where(Attendance.action_type == action_type.strip().lower())
    if date_val:
        query = query.where(Attendance.attendance_date == date_val)

    query = query.order_by(Attendance.attendance_date.desc(), Attendance.scanned_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    records = result.scalars().all()
    return records

@router.get("/{attendance_id}", response_model=AttendanceResponse)
async def get_attendance(
    attendance_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Get a specific attendance record with ownership enforcement.
    """
    result = await db.execute(select(Attendance).where(Attendance.id == attendance_id))
    attendance = result.scalars().first()
    if not attendance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance record not found")

    # Ownership checks
    if current_user.role == "admin":
        return attendance

    student_res = await db.execute(select(Student).where(Student.id == attendance.student_id))
    student = student_res.scalars().first()

    if current_user.role == "parent":
        if not student or str(student.parent_id) != str(current_user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to other families' data")
        return attendance

    if current_user.role == "teacher":
        is_assigned = student and await is_student_assigned_to_teacher(db, student.id, current_user.id)
        if not is_assigned:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: student not on your route")
        return attendance

    if current_user.role == "driver":
        driver_res = await db.execute(select(Driver.id).where(Driver.user_id == str(current_user.id)))
        driver = driver_res.scalars().first()
        if not driver:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        buses_res = await db.execute(select(Bus.id).where(Bus.driver_id == driver.id))
        driver_bus_ids = {str(b[0]) for b in buses_res.fetchall()}
        routes_res = await db.execute(select(Route.id, Route.bus_id).where(Route.driver_id == driver.id))
        driver_route_ids = set()
        for r_id, b_id in routes_res.fetchall():
            driver_route_ids.add(str(r_id))
            if b_id:
                driver_bus_ids.add(str(b_id))
        is_driver_assigned = (
            (attendance.bus_id and str(attendance.bus_id) in driver_bus_ids) or
            (attendance.route_id and str(attendance.route_id) in driver_route_ids)
        )
        if not is_driver_assigned:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: not your bus or route")
        return attendance

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

@router.put("/{attendance_id}", response_model=AttendanceResponse)
async def update_attendance(
    attendance_id: str,
    attendance_in: AttendanceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Update attendance status. Only status may be changed (Amendment 4).
    Teachers can only update records for students on their assigned route/bus within the last 7 days.
    """
    if current_user.role not in ("admin", "teacher"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators and teachers can modify attendance records."
        )

    result = await db.execute(select(Attendance).where(Attendance.id == attendance_id))
    attendance = result.scalars().first()
    if not attendance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance record not found")

    if current_user.role == "teacher":
        today_ist = get_kolkata_today()
        cutoff_date = today_ist - timedelta(days=7)
        if attendance.attendance_date < cutoff_date:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Teachers can only modify attendance records within the last 7 days (cutoff: {cutoff_date.isoformat()})."
            )

        is_assigned = await is_student_assigned_to_teacher(
            db, str(attendance.student_id), current_user.id, target_date=attendance.attendance_date
        )
        if not is_assigned:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to update attendance for this student: student is not on your route on this date."
            )

    was_absent = attendance.status == "absent"

    attendance.status = attendance_in.status
    attendance.scanned_at = datetime.now(timezone.utc)
    attendance.scanned_by = str(current_user.id)

    await db.commit()
    await db.refresh(attendance)

    if attendance_in.status == "absent" and not was_absent:
        await notify_parent_on_absent(
            db,
            str(attendance.student_id),
            attendance.attendance_date,
            attendance.action_type,
            str(current_user.id)
        )

    return attendance

@router.delete("/{attendance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attendance(
    attendance_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Delete an attendance record (Admin only per Amendment 4; teachers correct via upsert/update).
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can delete attendance records."
        )

    result = await db.execute(select(Attendance).where(Attendance.id == attendance_id))
    attendance = result.scalars().first()
    if not attendance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance record not found")

    await db.delete(attendance)
    await db.commit()
    return None
