from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict

class RouteBase(BaseModel):
    name: str
    start_location: str
    end_location: str
    bus_id: Optional[str] = None
    driver_id: Optional[str] = None
    waypoints: Optional[List[Dict[str, Any]]] = []
    scheduled_start_time: Optional[str] = None
    scheduled_end_time: Optional[str] = None
    status: Optional[str] = "planned"  # planned, in_progress, completed, cancelled

class RouteCreate(RouteBase):
    pass

class RouteUpdate(BaseModel):
    name: Optional[str] = None
    start_location: Optional[str] = None
    end_location: Optional[str] = None
    bus_id: Optional[str] = None
    driver_id: Optional[str] = None
    waypoints: Optional[List[Dict[str, Any]]] = None
    scheduled_start_time: Optional[str] = None
    scheduled_end_time: Optional[str] = None
    status: Optional[str] = None

class RouteResponse(RouteBase):
    id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
