from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict

class DriverBase(BaseModel):
    license_number: str
    phone: str
    status: Optional[str] = "active"  # active, inactive, on_duty
    user_id: Optional[str] = None

class DriverCreate(DriverBase):
    pass

class DriverUpdate(BaseModel):
    license_number: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None
    user_id: Optional[str] = None

class DriverResponse(DriverBase):
    id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
