from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field


class GenerateOtpRequest(BaseModel):
    email: EmailStr
    is_captcha_resend: bool = False


class GenerateOtpResponse(BaseModel):
    status: str  # "otp_sent" | "captcha_required"
    message: str
    otp_attempts: int = 0
    captcha_resends: int = 0
    captcha_id: Optional[str] = None
    captcha_svg: Optional[str] = None


class VerifyCaptchaRequest(BaseModel):
    email: EmailStr
    captcha_id: str
    captcha_answer: str


class VerifyCaptchaResponse(BaseModel):
    status: str  # "otp_sent"
    message: str


class VerifyOtpRequest(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=4, max_length=8)


class VerifyOtpResponse(BaseModel):
    verified: bool
    verification_token: str
    message: str


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    verification_token: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str


class SessionCreate(BaseModel):
    title: Optional[str] = "New Session"
    workspace_path: str


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SessionOut(BaseModel):
    id: str
    title: Optional[str] = None
    workspace_path: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SessionDetailOut(SessionOut):
    messages: List[MessageOut] = []