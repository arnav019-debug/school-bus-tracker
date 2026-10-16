from datetime import datetime
from typing import Optional, Any, Dict
from pydantic import BaseModel, ConfigDict, Field

class DeviceTokenRegister(BaseModel):
    token: str = Field(..., min_length=1, max_length=500, description="Push notification token (FCM/APNS)")
    platform: str = Field("android", description="Device platform (android, ios, web)")

class DeviceTokenUnregister(BaseModel):
    token: str = Field(..., min_length=1, max_length=500, description="Push notification token to remove")

class DeviceTokenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    token: str
    platform: str
    created_at: datetime
    updated_at: datetime

class NotificationLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    title: str
    body: str
    data_payload: Optional[Dict[str, Any]] = None
    status: str
    error_message: Optional[str] = None
    sent_at: datetime
