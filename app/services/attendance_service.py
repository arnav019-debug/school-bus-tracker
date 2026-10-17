import zoneinfo
from datetime import datetime, timezone, date
from typing import List, Optional, Dict, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.models.attendance import Attendance
from app.models.student import Student
from app.models.route import Route
from app.models.bus import Bus
from app.models.route_change_request import RouteChangeRequest
from app.schemas.attendance import StudentRosterItem

KOLKATA_TZ = zoneinfo.ZoneInfo("Asia/Kolkata")

def get_kolkata_today() -> date:
    """Returns today's date in Asia/Kolkata timezone."""
    return datetime.now(KOLKATA_TZ).date()

async def get_teacher_route_ids(db: AsyncSession, teacher_id: str) -> List[str]:
    """Returns all route IDs assigned to a specific teacher."""
    result = await db.execute(
        select(Route.id).where(Route.teacher_id == str(teacher_id))
    )
    return [str(r[0]) for r in result.fetchall()]

async def get_effective_route_and_bus_for_student(
    db: AsyncSession,
    student_id: str,
    target_date: date
) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (effective_route_id, effective_bus_id) for a student on target_date.
    Checks for an approved RouteChangeRequest covering target_date.
    If none exists, falls back to the student's permanent route and its associated bus.
    """
    # 1. Check for approved temporary change request
    req_res = await db.execute(
        select(RouteChangeRequest).where(
            RouteChangeRequest.student_id == str(student_id),
            RouteChangeRequest.status == "approved",
            RouteChangeRequest.start_date <= target_date,
            RouteChangeRequest.end_date >= target_date
        )
    )
    active_req = req_res.scalars().first()

    if active_req:
        target_route_id = str(active_req.target_route_id)
        target_bus_id = str(active_req.target_bus_id) if active_req.target_bus_id else None
        if not target_bus_id:
            route_res = await db.execute(select(Route.bus_id).where(Route.id == target_route_id))
            r_bus = route_res.scalars().first()
            if r_bus:
                target_bus_id = str(r_bus)
        return target_route_id, target_bus_id

    # 2. Permanent assignment fallback
    student_res = await db.execute(select(Student).where(Student.id == str(student_id)))
    student = student_res.scalars().first()
    if not student or not student.route_id:
        return None, None

    perm_route_id = str(student.route_id)
    route_res = await db.execute(select(Route.bus_id).where(Route.id == perm_route_id))
    r_bus = route_res.scalars().first()
    perm_bus_id = str(r_bus) if r_bus else None
    return perm_route_id, perm_bus_id

async def is_student_assigned_to_teacher(
    db: AsyncSession,
    student_id: str,
    teacher_id: str,
    target_date: Optional[date] = None
) -> bool:
    """Check if a student's effective route belongs to the teacher."""
    teacher_routes = await get_teacher_route_ids(db, teacher_id)
    if not teacher_routes:
        return False

    eff_date = target_date or get_kolkata_today()
    eff_route, _ = await get_effective_route_and_bus_for_student(db, student_id, eff_date)
    return eff_route in teacher_routes if eff_route else False

async def get_students_for_teacher(
    db: AsyncSession,
    teacher_id: str,
    target_date: date,
    action_type: str = "pickup"
) -> List[StudentRosterItem]:
    """
    Reusable roster query: teacher -> routes -> bus -> students.
    Seamlessly integrates effective route overrides from approved RouteChangeRequests.
    """
    # 1. Fetch routes assigned to this teacher
    routes_res = await db.execute(
        select(Route).where(Route.teacher_id == str(teacher_id))
    )
    routes = routes_res.scalars().all()
    if not routes:
        return []

    route_map: Dict[str, Route] = {str(r.id): r for r in routes}
    teacher_route_ids = set(route_map.keys())

    # 2. Candidate students:
    # A) Permanently assigned to teacher's routes
    perm_students_res = await db.execute(
        select(Student).where(Student.route_id.in_(list(teacher_route_ids)))
    )
    perm_students = perm_students_res.scalars().all()

    # B) Temporarily transferred to teacher's routes on target_date
    transferred_reqs_res = await db.execute(
        select(RouteChangeRequest.student_id).where(
            RouteChangeRequest.target_route_id.in_(list(teacher_route_ids)),
            RouteChangeRequest.status == "approved",
            RouteChangeRequest.start_date <= target_date,
            RouteChangeRequest.end_date >= target_date
        )
    )
    transferred_student_ids = [str(r[0]) for r in transferred_reqs_res.fetchall()]

    all_candidate_ids = set(str(s.id) for s in perm_students) | set(transferred_student_ids)
    if not all_candidate_ids:
        return []

    # Fetch full student objects for all candidates
    all_students_res = await db.execute(
        select(Student).where(Student.id.in_(list(all_candidate_ids))).order_by(Student.last_name, Student.first_name)
    )
    all_students = all_students_res.scalars().all()

    # Filter to students whose effective route for target_date is currently in teacher_route_ids
    active_students: List[Tuple[Student, str, Optional[str]]] = []
    for s in all_students:
        eff_route_id, eff_bus_id = await get_effective_route_and_bus_for_student(db, str(s.id), target_date)
        if eff_route_id and eff_route_id in teacher_route_ids:
            active_students.append((s, eff_route_id, eff_bus_id))

    if not active_students:
        return []

    # Fetch any routes/buses needed that might not be in initial map
    active_bus_ids = [bus_id for _, _, bus_id in active_students if bus_id]
    bus_map: Dict[str, Bus] = {}
    if active_bus_ids:
        buses_res = await db.execute(select(Bus).where(Bus.id.in_(active_bus_ids)))
        bus_map = {str(b.id): b for b in buses_res.scalars().all()}

    # Fetch existing attendance records for target_date
    student_ids = [str(s.id) for s, _, _ in active_students]
    att_res = await db.execute(
        select(Attendance).where(
            Attendance.student_id.in_(student_ids),
            Attendance.attendance_date == target_date,
            Attendance.action_type == action_type
        )
    )
    attendance_records = att_res.scalars().all()
    att_map: Dict[str, Attendance] = {str(a.student_id): a for a in attendance_records}

    # Build roster response items
    roster: List[StudentRosterItem] = []
    for student, eff_route_id, eff_bus_id in active_students:
        route = route_map.get(eff_route_id)
        route_name = route.name if route else None
        bus = bus_map.get(eff_bus_id) if eff_bus_id else None
        bus_number = bus.bus_number if bus else None

        att = att_map.get(str(student.id))
        status = att.status if att else None
        att_id = str(att.id) if att else None

        roster.append(StudentRosterItem(
            student_id=str(student.id),
            first_name=student.first_name,
            last_name=student.last_name,
            grade=student.grade,
            pickup_stop=student.pickup_stop,
            dropoff_stop=student.dropoff_stop,
            route_id=eff_route_id,
            route_name=route_name,
            bus_id=eff_bus_id,
            bus_number=bus_number,
            status=status,
            attendance_id=att_id,
            action_type=action_type,
        ))

    return roster

async def get_students_for_driver(
    db: AsyncSession,
    driver_profile_id: str,
    target_date: date,
    action_type: str = "pickup"
) -> List[StudentRosterItem]:
    """
    Roster query for drivers: driver -> buses & routes -> effective students on target_date.
    Respects approved RouteChangeRequests for target_date.
    """
    from app.models.driver import Driver
    driver_res = await db.execute(select(Driver).where(Driver.user_id == str(driver_profile_id)))
    driver = driver_res.scalars().first()
    if not driver:
        return []

    # 1. Driver's direct buses
    buses_direct = await db.execute(select(Bus).where(Bus.driver_id == driver.id))
    direct_buses = buses_direct.scalars().all()
    driver_bus_ids = {str(b.id) for b in direct_buses}

    # 2. Driver's direct routes
    routes_direct = await db.execute(select(Route).where(Route.driver_id == driver.id))
    direct_routes = routes_direct.scalars().all()
    driver_route_ids = {str(r.id) for r in direct_routes}
    for r in direct_routes:
        if r.bus_id:
            driver_bus_ids.add(str(r.bus_id))

    # 3. Routes belonging to any of driver's buses
    if driver_bus_ids:
        bus_routes = await db.execute(select(Route).where(Route.bus_id.in_(list(driver_bus_ids))))
        for r in bus_routes.scalars().all():
            driver_route_ids.add(str(r.id))

    if not driver_route_ids and not driver_bus_ids:
        return []

    # 4. Fetch candidate students:
    # Permanently on route
    perm_students_res = await db.execute(
        select(Student).where(Student.route_id.in_(list(driver_route_ids)))
    )
    perm_students = perm_students_res.scalars().all()

    # Temporarily transferred to these routes or buses on target_date
    transfer_res = await db.execute(
        select(RouteChangeRequest.student_id).where(
            or_(
                RouteChangeRequest.target_route_id.in_(list(driver_route_ids)),
                RouteChangeRequest.target_bus_id.in_(list(driver_bus_ids)),
            ),
            RouteChangeRequest.status == "approved",
            RouteChangeRequest.start_date <= target_date,
            RouteChangeRequest.end_date >= target_date,
        )
    )
    transfer_student_ids = [str(r[0]) for r in transfer_res.fetchall()]

    all_candidate_ids = set(str(s.id) for s in perm_students) | set(transfer_student_ids)
    if not all_candidate_ids:
        return []

    all_students_res = await db.execute(
        select(Student).where(Student.id.in_(list(all_candidate_ids))).order_by(Student.last_name, Student.first_name)
    )
    all_students = all_students_res.scalars().all()

    # Filter to students whose effective route or bus matches driver on target_date
    active_students: List[Tuple[Student, str, Optional[str]]] = []
    for s in all_students:
        eff_route_id, eff_bus_id = await get_effective_route_and_bus_for_student(db, str(s.id), target_date)
        if (eff_route_id and eff_route_id in driver_route_ids) or (eff_bus_id and eff_bus_id in driver_bus_ids):
            active_students.append((s, eff_route_id, eff_bus_id))

    if not active_students:
        return []

    # Fetch routes and buses for metadata
    needed_route_ids = [r_id for _, r_id, _ in active_students if r_id]
    needed_bus_ids = [b_id for _, _, b_id in active_students if b_id]

    route_map: Dict[str, Route] = {}
    if needed_route_ids:
        routes_res = await db.execute(select(Route).where(Route.id.in_(needed_route_ids)))
        route_map = {str(r.id): r for r in routes_res.scalars().all()}

    bus_map: Dict[str, Bus] = {}
    if needed_bus_ids:
        buses_res = await db.execute(select(Bus).where(Bus.id.in_(needed_bus_ids)))
        bus_map = {str(b.id): b for b in buses_res.scalars().all()}

    # Fetch attendance
    student_ids = [str(s.id) for s, _, _ in active_students]
    att_res = await db.execute(
        select(Attendance).where(
            Attendance.student_id.in_(student_ids),
            Attendance.attendance_date == target_date,
            Attendance.action_type == action_type
        )
    )
    att_map = {str(a.student_id): a for a in att_res.scalars().all()}

    roster: List[StudentRosterItem] = []
    for student, eff_route_id, eff_bus_id in active_students:
        route = route_map.get(eff_route_id) if eff_route_id else None
        route_name = route.name if route else None
        bus = bus_map.get(eff_bus_id) if eff_bus_id else None
        bus_number = bus.bus_number if bus else None

        att = att_map.get(str(student.id))
        status_val = att.status if att else None
        att_id = str(att.id) if att else None

        roster.append(StudentRosterItem(
            student_id=str(student.id),
            first_name=student.first_name,
            last_name=student.last_name,
            grade=student.grade,
            pickup_stop=student.pickup_stop,
            dropoff_stop=student.dropoff_stop,
            route_id=eff_route_id,
            route_name=route_name,
            bus_id=eff_bus_id,
            bus_number=bus_number,
            status=status_val,
            attendance_id=att_id,
            action_type=action_type,
        ))

    return roster


async def get_parent_accessible_route_ids(db: AsyncSession, parent_user_id: str, target_date: Optional[date] = None) -> List[str]:
    """Returns all route IDs assigned to children of this parent (permanent + effective)."""
    date_val = target_date or get_kolkata_today()
    students_res = await db.execute(select(Student.id, Student.route_id).where(Student.parent_id == str(parent_user_id)))
    rows = students_res.all()
    route_ids = set()
    for s_id, s_route in rows:
        if s_route:
            route_ids.add(str(s_route))
        eff_route, _ = await get_effective_route_and_bus_for_student(db, str(s_id), date_val)
        if eff_route:
            route_ids.add(str(eff_route))
    return list(route_ids)


async def get_parent_accessible_bus_ids(db: AsyncSession, parent_user_id: str, target_date: Optional[date] = None) -> List[str]:
    """Returns all bus IDs associated with children of this parent."""
    date_val = target_date or get_kolkata_today()
    students_res = await db.execute(select(Student.id, Student.route_id).where(Student.parent_id == str(parent_user_id)))
    rows = students_res.all()
    bus_ids = set()
    for s_id, s_route in rows:
        eff_route, eff_bus = await get_effective_route_and_bus_for_student(db, str(s_id), date_val)
        if eff_bus:
            bus_ids.add(str(eff_bus))
        elif s_route:
            r_res = await db.execute(select(Route.bus_id).where(Route.id == str(s_route)))
            b = r_res.scalars().first()
            if b:
                bus_ids.add(str(b))
    return list(bus_ids)


async def get_parent_accessible_driver_ids(db: AsyncSession, parent_user_id: str, target_date: Optional[date] = None) -> List[str]:
    """Returns all driver IDs associated with children of this parent (driver contact)."""
    bus_ids = await get_parent_accessible_bus_ids(db, parent_user_id, target_date)
    route_ids = await get_parent_accessible_route_ids(db, parent_user_id, target_date)
    driver_ids = set()
    if bus_ids:
        b_res = await db.execute(select(Bus.driver_id).where(Bus.id.in_(bus_ids), Bus.driver_id.isnot(None)))
        for d in b_res.scalars().all():
            driver_ids.add(str(d))
    if route_ids:
        r_res = await db.execute(select(Route.driver_id).where(Route.id.in_(route_ids), Route.driver_id.isnot(None)))
        for d in r_res.scalars().all():
            driver_ids.add(str(d))
    return list(driver_ids)


async def get_driver_accessible_route_ids(db: AsyncSession, driver_user_id: str) -> List[str]:
    """Returns all route IDs assigned to this driver."""
    from app.models.driver import Driver
    d_res = await db.execute(select(Driver.id).where(Driver.user_id == str(driver_user_id)))
    driver_id = d_res.scalars().first()
    if not driver_id:
        return []
    r_res = await db.execute(select(Route.id).where(Route.driver_id == driver_id))
    return [str(r) for r in r_res.scalars().all()]


async def get_driver_accessible_bus_ids(db: AsyncSession, driver_user_id: str) -> List[str]:
    """Returns all bus IDs assigned to this driver directly or via route."""
    from app.models.driver import Driver
    d_res = await db.execute(select(Driver.id).where(Driver.user_id == str(driver_user_id)))
    driver_id = d_res.scalars().first()
    if not driver_id:
        return []
    bus_ids = set()
    b_res = await db.execute(select(Bus.id).where(Bus.driver_id == driver_id))
    for b in b_res.scalars().all():
        bus_ids.add(str(b))
    r_res = await db.execute(select(Route.bus_id).where(Route.driver_id == driver_id, Route.bus_id.isnot(None)))
    for b in r_res.scalars().all():
        bus_ids.add(str(b))
    return list(bus_ids)


async def get_teacher_accessible_bus_ids(db: AsyncSession, teacher_user_id: str) -> List[str]:
    """Returns all bus IDs assigned to routes managed by this teacher."""
    r_res = await db.execute(select(Route.bus_id).where(Route.teacher_id == str(teacher_user_id), Route.bus_id.isnot(None)))
    return [str(b) for b in r_res.scalars().all()]


async def get_teacher_accessible_driver_ids(db: AsyncSession, teacher_user_id: str) -> List[str]:
    """Returns all driver IDs assigned to routes or buses managed by this teacher."""
    driver_ids = set()
    r_res = await db.execute(select(Route.driver_id, Route.bus_id).where(Route.teacher_id == str(teacher_user_id)))
    for did, bid in r_res.all():
        if did:
            driver_ids.add(str(did))
        if bid:
            b_res = await db.execute(select(Bus.driver_id).where(Bus.id == bid, Bus.driver_id.isnot(None)))
            b_driver = b_res.scalars().first()
            if b_driver:
                driver_ids.add(str(b_driver))
    return list(driver_ids)


