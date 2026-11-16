from typing import List, Optional
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str = Field(..., description="Role of the message sender: 'user', 'assistant', or 'system'")
    content: str = Field(..., description="The message content")


class ChatRequest(BaseModel):
    session_id: str = Field(..., description="ID of the active chat session")
    content: str = Field(..., description="User prompt text")


class ChatResponse(BaseModel):
    session_id: str
    response: str
    status: str = "success"


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"