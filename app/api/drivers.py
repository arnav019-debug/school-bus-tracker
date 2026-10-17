from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.driver import Driver
from app.models.profile import Profile
from app.schemas.driver import DriverCreate, DriverUpdate, DriverResponse
from app.api.deps import get_current_user

router = APIRouter()

@router.get("", response_model=List[DriverResponse])
@router.get("/", response_model=List[DriverResponse], include_in_schema=False)
async def list_drivers(
    status: Optional[str] = Query(None, description="Filter by driver status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100, description="Pagination limit (max 100)"),
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Retrieve drivers scoped by role:
    - Admin: all drivers
    - Driver: only self
    - Parent: drivers assigned to child's routes/buses
    - Teacher: drivers assigned to teacher's routes/buses
    """
    query = select(Driver)
    if current_user.role == "driver":
        query = query.where(Driver.user_id == str(current_user.id))
    elif current_user.role == "parent":
        from app.services.attendance_service import get_parent_accessible_driver_ids
        p_drivers = await get_parent_accessible_driver_ids(db, str(current_user.id))
        if not p_drivers:
            return []
        query = query.where(Driver.id.in_(p_drivers))
    elif current_user.role == "teacher":
        from app.services.attendance_service import get_teacher_accessible_driver_ids
        t_drivers = await get_teacher_accessible_driver_ids(db, str(current_user.id))
        if not t_drivers:
            return []
        query = query.where(Driver.id.in_(t_drivers))

    if status:
        query = query.where(Driver.status == status)

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    drivers = result.scalars().all()
    return drivers

@router.post("", response_model=DriverResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=DriverResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_driver(
    driver_in: DriverCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Create a new driver record (Admin only).
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage drivers."
        )

    # Check for existing license number
    existing = await db.execute(select(Driver).where(Driver.license_number == driver_in.license_number))
    if existing.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Driver with this license number already exists."
        )

    driver = Driver(**driver_in.model_dump())
    db.add(driver)
    await db.commit()
    await db.refresh(driver)
    return driver

@router.get("/{driver_id}", response_model=DriverResponse)
async def get_driver(
    driver_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Get a specific driver by ID with role authorization check.
    """
    result = await db.execute(select(Driver).where(Driver.id == driver_id))
    driver = result.scalars().first()
    if not driver:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver not found"
        )

    if current_user.role == "driver":
        if not driver.user_id or str(driver.user_id) != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to other drivers' information."
            )
    elif current_user.role == "parent":
        from app.services.attendance_service import get_parent_accessible_driver_ids
        p_drivers = await get_parent_accessible_driver_ids(db, str(current_user.id))
        if str(driver.id) not in p_drivers:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: driver not assigned to your child's route."
            )
    elif current_user.role == "teacher":
        from app.services.attendance_service import get_teacher_accessible_driver_ids
        t_drivers = await get_teacher_accessible_driver_ids(db, str(current_user.id))
        if str(driver.id) not in t_drivers:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: driver not assigned to your route."
            )

    return driver

@router.put("/{driver_id}", response_model=DriverResponse)
async def update_driver(
    driver_id: str,
    driver_in: DriverUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Update a driver record (Admin only).
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage drivers."
        )

    result = await db.execute(select(Driver).where(Driver.id == driver_id))
    driver = result.scalars().first()
    if not driver:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver not found"
        )

    update_data = driver_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(driver, field, value)

    await db.commit()
    await db.refresh(driver)
    return driver

@router.delete("/{driver_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_driver(
    driver_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Profile = Depends(get_current_user)
):
    """
    Delete a driver record (Admin only).
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage drivers."
        )

    result = await db.execute(select(Driver).where(Driver.id == driver_id))
    driver = result.scalars().first()
    if not driver:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver not found"
        )

    await db.delete(driver)
    await db.commit()
    return None

