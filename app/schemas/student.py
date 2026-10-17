from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict

class StudentBase(BaseModel):
    first_name: str
    last_name: str
    grade: Optional[str] = None
    parent_id: Optional[str] = None
    route_id: Optional[str] = None
    pickup_stop: Optional[str] = None
    dropoff_stop: Optional[str] = None

class StudentCreate(StudentBase):
    qr_code_id: Optional[str] = None

class StudentUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    grade: Optional[str] = None
    parent_id: Optional[str] = None
    route_id: Optional[str] = None
    pickup_stop: Optional[str] = None
    dropoff_stop: Optional[str] = None
    qr_code_id: Optional[str] = None

class DriverContact(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    full_name: Optional[str] = None
    license_number: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = "active"

class StudentResponse(StudentBase):
    id: str
    qr_code_id: str
    effective_route_id: Optional[str] = None
    effective_bus_id: Optional[str] = None
    effective_driver: Optional[DriverContact] = None
    effective_driver_contact: Optional[DriverContact] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

