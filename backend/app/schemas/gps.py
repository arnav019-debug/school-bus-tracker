from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class GpsLogCreate(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    speed: Optional[float] = Field(default=0.0, ge=0)
    heading: Optional[float] = Field(default=None, ge=0, le=360)
    route_id: Optional[str] = None
    timestamp: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class GpsLogResponse(BaseModel):
    id: int
    bus_id: str
    route_id: Optional[str] = None
    latitude: float
    longitude: float
    speed: Optional[float] = None
    heading: Optional[float] = None
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)
