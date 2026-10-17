from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.route import Route
from app.models.profile import Profile
from app.schemas.route import RouteCreate, RouteUpdate, RouteResponse
from app.api.deps import get_current_user

router = APIRouter()

@router.get("", response_model=List[RouteResponse])
@router.get("/", response_model=List[RouteResponse], include_in_schema=False)
async def list_routes(
    status: Optional[str] = Query(None, description="Filter by route status"),
    bus_id: Optional[str] = Query(None, description="Filter by bus ID"),
    driver_id: Optional[str] = Query(None, description="Filter by driver ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100, description="Pagination limit (max 100)"),
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Retrieve all routes with optional filtering and pagination.
    """
    query = select(Route)
    if current_user.role == "teacher":
        query = query.where(Route.teacher_id == str(current_user.id))
    elif current_user.role == "driver":
        from app.services.attendance_service import get_driver_accessible_route_ids
        d_routes = await get_driver_accessible_route_ids(db, str(current_user.id))
        if not d_routes:
            return []
        query = query.where(Route.id.in_(d_routes))
    elif current_user.role == "parent":
        from app.services.attendance_service import get_parent_accessible_route_ids
        p_routes = await get_parent_accessible_route_ids(db, str(current_user.id))
        if not p_routes:
            return []
        query = query.where(Route.id.in_(p_routes))

    if status:
        query = query.where(Route.status == status)
    if bus_id:
        query = query.where(Route.bus_id == bus_id)
    if driver_id:
        query = query.where(Route.driver_id == driver_id)

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    routes = result.scalars().all()
    return routes

from datetime import time as time_type

def _parse_time(val):
    if not val:
        return None
    if isinstance(val, time_type):
        return val
    try:
        return time_type.fromisoformat(str(val))
    except Exception:
        return None

@router.post("", response_model=RouteResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=RouteResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_route(
    route_in: RouteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Create a new route record.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage routes."
        )

    from app.models.bus import Bus
    data = route_in.model_dump()
    if data.get("scheduled_start_time"):
        data["scheduled_start_time"] = _parse_time(data["scheduled_start_time"])
    if data.get("scheduled_end_time"):
        data["scheduled_end_time"] = _parse_time(data["scheduled_end_time"])
    route = Route(**data)
    db.add(route)
    if route.bus_id and route.driver_id:
        bus_res = await db.execute(select(Bus).where(Bus.id == route.bus_id))
        bus = bus_res.scalars().first()
        if bus and not bus.driver_id:
            bus.driver_id = route.driver_id
    await db.commit()
    await db.refresh(route)
    return route

@router.get("/{route_id}", response_model=RouteResponse)
async def get_route(
    route_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Get a specific route by ID.
    """
    result = await db.execute(select(Route).where(Route.id == route_id))
    route = result.scalars().first()
    if not route:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route not found"
        )

    if current_user.role == "teacher":
        if not route.teacher_id or str(route.teacher_id) != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: not your assigned route."
            )
    elif current_user.role == "driver":
        from app.services.attendance_service import get_driver_accessible_route_ids
        d_routes = await get_driver_accessible_route_ids(db, str(current_user.id))
        if str(route.id) not in d_routes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: not your assigned route."
            )
    elif current_user.role == "parent":
        from app.services.attendance_service import get_parent_accessible_route_ids
        p_routes = await get_parent_accessible_route_ids(db, str(current_user.id))
        if str(route.id) not in p_routes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: not your child's route."
            )

    return route

@router.put("/{route_id}", response_model=RouteResponse)
async def update_route(
    route_id: str,
    route_in: RouteUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Update a route record.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage routes."
        )

    from app.models.bus import Bus
    result = await db.execute(select(Route).where(Route.id == route_id))
    route = result.scalars().first()
    if not route:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route not found"
        )

    update_data = route_in.model_dump(exclude_unset=True)
    if "scheduled_start_time" in update_data and update_data["scheduled_start_time"]:
        update_data["scheduled_start_time"] = _parse_time(update_data["scheduled_start_time"])
    if "scheduled_end_time" in update_data and update_data["scheduled_end_time"]:
        update_data["scheduled_end_time"] = _parse_time(update_data["scheduled_end_time"])
    for field, value in update_data.items():
        setattr(route, field, value)

    if route.bus_id and route.driver_id:
        bus_res = await db.execute(select(Bus).where(Bus.id == route.bus_id))
        bus = bus_res.scalars().first()
        if bus and not bus.driver_id:
            bus.driver_id = route.driver_id

    await db.commit()
    await db.refresh(route)
    return route

@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route(
    route_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Delete a route record.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage routes."
        )

    result = await db.execute(select(Route).where(Route.id == route_id))
    route = result.scalars().first()
    if not route:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route not found"
        )

    await db.delete(route)
    await db.commit()
    return None
