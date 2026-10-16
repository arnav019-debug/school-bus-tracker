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
    from app.models.bus import Bus
    route = Route(**route_in.model_dump())
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
    from app.models.bus import Bus
    result = await db.execute(select(Route).where(Route.id == route_id))
    route = result.scalars().first()
    if not route:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route not found"
        )

    update_data = route_in.model_dump(exclude_unset=True)
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
