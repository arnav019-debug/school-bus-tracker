from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

class RouteChangeRequestCreate(BaseModel):
    student_id: str = Field(..., description="ID of the student requesting temporary change")
    target_route_id: str = Field(..., description="Target temporary route ID")
    target_bus_id: Optional[str] = Field(None, description="Target bus ID (auto-resolved if null)")
    start_date: date = Field(..., description="Start date of temporary change (YYYY-MM-DD)")
    end_date: date = Field(..., description="End date of temporary change (YYYY-MM-DD)")
    reason: str = Field(..., min_length=3, max_length=500, description="Reason for the temporary change")

class RouteChangeRequestReview(BaseModel):
    review_notes: Optional[str] = Field(None, max_length=500, description="Notes from administrator")

class RouteChangeRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    student_id: str
    requested_by: str
    target_route_id: str
    target_bus_id: Optional[str] = None
    start_date: date
    end_date: date
    reason: str
    status: str
    reviewed_by: Optional[str] = None
    review_notes: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    student_name: Optional[str] = None
    target_route_name: Optional[str] = None
