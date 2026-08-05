from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GpsLogCreate(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    speed: float | None = Field(default=0.0, ge=0)
    heading: float | None = Field(default=None, ge=0, le=360)
    route_id: str | None = None
    timestamp: datetime | None = None


class GpsLogResponse(BaseModel):
    id: int
    bus_id: str
    route_id: str | None = None
    latitude: float
    longitude: float
    speed: float | None = None
    heading: float | None = None
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)
