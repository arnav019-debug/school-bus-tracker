from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, field_validator

def normalize_status(val: str) -> str:
    cleaned = (val or "").strip().lower()
    if cleaned in ("present", "boarded", "dropped", "disembarked"):
        return "present"
    if cleaned == "absent":
        return "absent"
    raise ValueError(f"Invalid attendance status: {val}. Must be 'present' or 'absent'.")

class AttendanceCreate(BaseModel):
    student_id: str
    bus_id: Optional[str] = None
    route_id: Optional[str] = None
    attendance_date: Optional[date] = None
    status: str
    action_type: str = "pickup"

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        return normalize_status(v)

    @field_validator("action_type")
    @classmethod
    def validate_action_type(cls, v: str) -> str:
        cleaned = (v or "").strip().lower()
        if cleaned not in ("pickup", "dropoff"):
            raise ValueError(f"Invalid action_type: {v}. Must be 'pickup' or 'dropoff'.")
        return cleaned

class AttendanceUpdate(BaseModel):
    # Amendment 4: PUT may change status only
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        return normalize_status(v)

class AttendanceResponse(BaseModel):
    id: str
    student_id: str
    bus_id: Optional[str] = None
    route_id: Optional[str] = None
    attendance_date: date
    status: str
    action_type: str
    scanned_at: datetime
    scanned_by: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class StudentRosterItem(BaseModel):
    student_id: str
    first_name: str
    last_name: str
    grade: Optional[str] = None
    pickup_stop: Optional[str] = None
    dropoff_stop: Optional[str] = None
    route_id: Optional[str] = None
    route_name: Optional[str] = None
    bus_id: Optional[str] = None
    bus_number: Optional[str] = None
    status: Optional[str] = None  # 'present', 'absent', or None if not yet marked
    attendance_id: Optional[str] = None
    action_type: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
