from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.database import get_db
from app.models.profile import Profile
from app.models.student import Student
from app.models.route import Route
from app.models.bus import Bus
from app.models.route_change_request import RouteChangeRequest
from app.schemas.route_change_request import (
    RouteChangeRequestCreate,
    RouteChangeRequestReview,
    RouteChangeRequestResponse,
)
from app.services.attendance_service import get_kolkata_today
from app.services.notification_service import notify_parent_on_route_change_review
from app.api.deps import get_current_user

router = APIRouter()

@router.post("", response_model=RouteChangeRequestResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=RouteChangeRequestResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_route_change_request(
    payload: RouteChangeRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Submit a temporary route/bus change request for a student.
    - Parents: can only submit for their own children.
    - Admins: can submit for any student.
    - Teachers/Drivers: forbidden.
    """
    if current_user.role not in ("admin", "parent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only parents and administrators can submit route change requests."
        )

    # 1. Fetch student
    student_res = await db.execute(select(Student).where(Student.id == payload.student_id))
    student = student_res.scalars().first()
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    # Parent ownership check
    if current_user.role == "parent" and str(student.parent_id) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only submit route change requests for your own children."
        )

    # 2. Date validations (Asia/Kolkata timezone)
    today = get_kolkata_today()
    if payload.start_date < today:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Start date cannot be in the past (today is {today.isoformat()})."
        )
    if payload.end_date < payload.start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="End date cannot be earlier than start date."
        )
    if (payload.end_date - payload.start_date).days > 30:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Temporary route change request cannot exceed 30 days."
        )

    # 3. Target route lookup & bus resolution
    target_route_res = await db.execute(select(Route).where(Route.id == payload.target_route_id))
    target_route = target_route_res.scalars().first()
    if not target_route:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target route not found")

    target_bus_id = payload.target_bus_id or (str(target_route.bus_id) if target_route.bus_id else None)

    # 4. Check for active/pending overlapping requests for the same student
    overlap_res = await db.execute(
        select(RouteChangeRequest).where(
            RouteChangeRequest.student_id == str(student.id),
            RouteChangeRequest.status.in_(["pending", "approved"]),
            RouteChangeRequest.start_date <= payload.end_date,
            RouteChangeRequest.end_date >= payload.start_date
        )
    )
    if overlap_res.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="There is already an active or pending route change request overlapping this date range."
        )

    # 5. Create request
    new_req = RouteChangeRequest(
        student_id=str(student.id),
        requested_by=str(current_user.id),
        target_route_id=str(target_route.id),
        target_bus_id=target_bus_id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        reason=payload.reason.strip(),
        status="pending"
    )
    db.add(new_req)
    await db.commit()
    await db.refresh(new_req)

    return RouteChangeRequestResponse(
        id=str(new_req.id),
        student_id=str(new_req.student_id),
        requested_by=str(new_req.requested_by),
        target_route_id=str(new_req.target_route_id),
        target_bus_id=new_req.target_bus_id,
        start_date=new_req.start_date,
        end_date=new_req.end_date,
        reason=new_req.reason,
        status=new_req.status,
        reviewed_by=new_req.reviewed_by,
        review_notes=new_req.review_notes,
        reviewed_at=new_req.reviewed_at,
        created_at=new_req.created_at,
        updated_at=new_req.updated_at,
        student_name=f"{student.first_name} {student.last_name}",
        target_route_name=target_route.name
    )

@router.get("", response_model=List[RouteChangeRequestResponse])
@router.get("/", response_model=List[RouteChangeRequestResponse], include_in_schema=False)
async def list_route_change_requests(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status ('pending', 'approved', 'rejected', 'cancelled')"),
    student_id: Optional[str] = Query(None, description="Filter by student ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100, description="Pagination limit (max 100)"),
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    List route change requests scoped by role:
    - Parents: only see their own submitted requests.
    - Admins: see all requests.
    - Teachers / Drivers: forbidden.
    """
    if current_user.role not in ("admin", "parent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access restricted to parents and administrators."
        )

    query = select(RouteChangeRequest)

    if current_user.role == "parent":
        query = query.where(RouteChangeRequest.requested_by == str(current_user.id))
    elif student_id:
        query = query.where(RouteChangeRequest.student_id == str(student_id))

    if status_filter:
        query = query.where(RouteChangeRequest.status == status_filter.strip().lower())

    query = query.order_by(RouteChangeRequest.created_at.desc()).offset(skip).limit(limit)
    res = await db.execute(query)
    requests = res.scalars().all()

    response_items = []
    for req in requests:
        # Load related names
        s_res = await db.execute(select(Student).where(Student.id == req.student_id))
        s = s_res.scalars().first()
        r_res = await db.execute(select(Route.name).where(Route.id == req.target_route_id))
        r_name = r_res.scalars().first()

        response_items.append(RouteChangeRequestResponse(
            id=str(req.id),
            student_id=str(req.student_id),
            requested_by=str(req.requested_by),
            target_route_id=str(req.target_route_id),
            target_bus_id=req.target_bus_id,
            start_date=req.start_date,
            end_date=req.end_date,
            reason=req.reason,
            status=req.status,
            reviewed_by=req.reviewed_by,
            review_notes=req.review_notes,
            reviewed_at=req.reviewed_at,
            created_at=req.created_at,
            updated_at=req.updated_at,
            student_name=f"{s.first_name} {s.last_name}" if s else None,
            target_route_name=r_name
        ))

    return response_items

@router.get("/{request_id}", response_model=RouteChangeRequestResponse)
async def get_route_change_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """Get single route change request with ownership checks."""
    res = await db.execute(select(RouteChangeRequest).where(RouteChangeRequest.id == request_id))
    req = res.scalars().first()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

    if current_user.role != "admin" and str(req.requested_by) != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    s_res = await db.execute(select(Student).where(Student.id == req.student_id))
    s = s_res.scalars().first()
    r_res = await db.execute(select(Route.name).where(Route.id == req.target_route_id))
    r_name = r_res.scalars().first()

    return RouteChangeRequestResponse(
        id=str(req.id),
        student_id=str(req.student_id),
        requested_by=str(req.requested_by),
        target_route_id=str(req.target_route_id),
        target_bus_id=req.target_bus_id,
        start_date=req.start_date,
        end_date=req.end_date,
        reason=req.reason,
        status=req.status,
        reviewed_by=req.reviewed_by,
        review_notes=req.review_notes,
        reviewed_at=req.reviewed_at,
        created_at=req.created_at,
        updated_at=req.updated_at,
        student_name=f"{s.first_name} {s.last_name}" if s else None,
        target_route_name=r_name
    )

@router.put("/{request_id}/approve", response_model=RouteChangeRequestResponse)
async def approve_route_change_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """Admin approves a pending route change request."""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only administrators can approve requests.")

    res = await db.execute(select(RouteChangeRequest).where(RouteChangeRequest.id == request_id))
    req = res.scalars().first()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

    if req.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve request with current status '{req.status}'"
        )

    req.status = "approved"
    req.reviewed_by = str(current_user.id)
    req.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(req)

    # Notify parent
    s_res = await db.execute(select(Student).where(Student.id == req.student_id))
    s = s_res.scalars().first()
    student_name = f"{s.first_name} {s.last_name}" if s else "Student"
    await notify_parent_on_route_change_review(
        db,
        parent_id=str(req.requested_by),
        student_name=student_name,
        status_decision="approved"
    )

    r_res = await db.execute(select(Route.name).where(Route.id == req.target_route_id))
    r_name = r_res.scalars().first()

    return RouteChangeRequestResponse(
        id=str(req.id),
        student_id=str(req.student_id),
        requested_by=str(req.requested_by),
        target_route_id=str(req.target_route_id),
        target_bus_id=req.target_bus_id,
        start_date=req.start_date,
        end_date=req.end_date,
        reason=req.reason,
        status=req.status,
        reviewed_by=req.reviewed_by,
        review_notes=req.review_notes,
        reviewed_at=req.reviewed_at,
        created_at=req.created_at,
        updated_at=req.updated_at,
        student_name=student_name,
        target_route_name=r_name
    )

@router.put("/{request_id}/reject", response_model=RouteChangeRequestResponse)
async def reject_route_change_request(
    request_id: str,
    payload: RouteChangeRequestReview,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """Admin rejects a pending route change request."""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only administrators can reject requests.")

    res = await db.execute(select(RouteChangeRequest).where(RouteChangeRequest.id == request_id))
    req = res.scalars().first()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

    if req.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reject request with current status '{req.status}'"
        )

    req.status = "rejected"
    req.reviewed_by = str(current_user.id)
    req.review_notes = payload.review_notes.strip() if payload.review_notes else None
    req.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(req)

    # Notify parent
    s_res = await db.execute(select(Student).where(Student.id == req.student_id))
    s = s_res.scalars().first()
    student_name = f"{s.first_name} {s.last_name}" if s else "Student"
    await notify_parent_on_route_change_review(
        db,
        parent_id=str(req.requested_by),
        student_name=student_name,
        status_decision="rejected",
        notes=req.review_notes
    )

    r_res = await db.execute(select(Route.name).where(Route.id == req.target_route_id))
    r_name = r_res.scalars().first()

    return RouteChangeRequestResponse(
        id=str(req.id),
        student_id=str(req.student_id),
        requested_by=str(req.requested_by),
        target_route_id=str(req.target_route_id),
        target_bus_id=req.target_bus_id,
        start_date=req.start_date,
        end_date=req.end_date,
        reason=req.reason,
        status=req.status,
        reviewed_by=req.reviewed_by,
        review_notes=req.review_notes,
        reviewed_at=req.reviewed_at,
        created_at=req.created_at,
        updated_at=req.updated_at,
        student_name=student_name,
        target_route_name=r_name
    )

@router.put("/{request_id}/cancel", response_model=RouteChangeRequestResponse)
async def cancel_route_change_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """Cancel a pending route change request (requester or admin)."""
    res = await db.execute(select(RouteChangeRequest).where(RouteChangeRequest.id == request_id))
    req = res.scalars().first()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

    if current_user.role != "admin" and str(req.requested_by) != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if req.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel request with status '{req.status}' (must be pending)"
        )

    req.status = "cancelled"
    await db.commit()
    await db.refresh(req)

    return RouteChangeRequestResponse(
        id=str(req.id),
        student_id=str(req.student_id),
        requested_by=str(req.requested_by),
        target_route_id=str(req.target_route_id),
        target_bus_id=req.target_bus_id,
        start_date=req.start_date,
        end_date=req.end_date,
        reason=req.reason,
        status=req.status,
        reviewed_by=req.reviewed_by,
        review_notes=req.review_notes,
        reviewed_at=req.reviewed_at,
        created_at=req.created_at,
        updated_at=req.updated_at
    )
