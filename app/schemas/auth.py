from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, EmailStr, ConfigDict

class UserRegister(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: Optional[str] = "parent"  # admin, staff, parent, driver
    phone: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserProfileResponse(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: str
    phone: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: Optional[str] = None
    user: UserProfileResponse

class TokenData(BaseModel):
    user_id: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ForgotPasswordResponse(BaseModel):
    message: str = "If an account with that email exists, a password reset link has been sent."

def validate_password_strength(password: str) -> str:
    import re
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter.")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one digit.")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>\-_]", password):
        raise ValueError("Password must contain at least one special character.")
    return password

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @classmethod
    def validate_password(cls, v: str) -> str:
        return validate_password_strength(v)

    def model_post_init(self, __context) -> None:
        validate_password_strength(self.new_password)

class ResetPasswordResponse(BaseModel):
    message: str = "Password has been successfully reset."
