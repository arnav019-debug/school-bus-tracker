from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict

class BusBase(BaseModel):
    bus_number: str
    license_plate: str
    capacity: int
    status: Optional[str] = "active"  # active, maintenance, out_of_service
    driver_id: Optional[str] = None

class BusCreate(BusBase):
    pass

class BusUpdate(BaseModel):
    bus_number: Optional[str] = None
    license_plate: Optional[str] = None
    capacity: Optional[int] = None
    status: Optional[str] = None
    driver_id: Optional[str] = None

class BusResponse(BusBase):
    id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
