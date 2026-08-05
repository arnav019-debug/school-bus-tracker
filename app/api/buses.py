from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.bus import Bus
from app.models.profile import Profile
from app.schemas.bus import BusCreate, BusUpdate, BusResponse
from app.api.deps import get_current_user

router = APIRouter()

@router.get("", response_model=List[BusResponse])
@router.get("/", response_model=List[BusResponse], include_in_schema=False)
async def list_buses(
    status: Optional[str] = Query(None, description="Filter by bus status"),
    driver_id: Optional[str] = Query(None, description="Filter by driver ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Retrieve all buses with optional filtering and pagination.
    """
    query = select(Bus)
    if status:
        query = query.where(Bus.status == status)
    if driver_id:
        query = query.where(Bus.driver_id == driver_id)
    
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    buses = result.scalars().all()
    return buses

@router.post("", response_model=BusResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=BusResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_bus(
    bus_in: BusCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Create a new bus record.
    """
    # Check for existing bus number or license plate
    existing = await db.execute(
        select(Bus).where((Bus.bus_number == bus_in.bus_number) | (Bus.license_plate == bus_in.license_plate))
    )
    if existing.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bus with this number or license plate already exists."
        )

    bus = Bus(**bus_in.model_dump())
    db.add(bus)
    await db.commit()
    await db.refresh(bus)
    return bus

@router.get("/{bus_id}", response_model=BusResponse)
async def get_bus(
    bus_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Get a specific bus by ID.
    """
    result = await db.execute(select(Bus).where(Bus.id == bus_id))
    bus = result.scalars().first()
    if not bus:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bus not found"
        )
    return bus

@router.put("/{bus_id}", response_model=BusResponse)
async def update_bus(
    bus_id: str,
    bus_in: BusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Update a bus record.
    """
    result = await db.execute(select(Bus).where(Bus.id == bus_id))
    bus = result.scalars().first()
    if not bus:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bus not found"
        )

    update_data = bus_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(bus, field, value)

    await db.commit()
    await db.refresh(bus)
    return bus

@router.delete("/{bus_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bus(
    bus_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Delete a bus record.
    """
    result = await db.execute(select(Bus).where(Bus.id == bus_id))
    bus = result.scalars().first()
    if not bus:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bus not found"
        )

    await db.delete(bus)
    await db.commit()
    return None
