from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator


class RequestStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"


class CreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_input: StrictStr = Field(..., description="Original natural-language request")

    @field_validator("user_input")
    @classmethod
    def validate_user_input(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("user_input must not be empty")
        return value


class RequestCreated(BaseModel):
    id: str


class RequestStatusResponse(BaseModel):
    id: str
    status: RequestStatus


class NotificationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    to: StrictStr
    message: StrictStr
    type: Literal["email", "sms"]

    @field_validator("to", "message")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("notification fields must not be empty")
        return value
