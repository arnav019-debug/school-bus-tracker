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

class StudentResponse(StudentBase):
    id: str
    qr_code_id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
