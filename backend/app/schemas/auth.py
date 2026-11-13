"""Pydantic schemas for authentication."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.user import UserResponse, validate_password_policy

PASSWORD_MAX_BYTES = 72


class LoginRequest(BaseModel):
    """JSON body for POST /api/v1/auth/login (used by the SPA / mobile app)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "arjun@brightloop.in",
                "password": "Admin@2026",
            }
        }
    )

    email: EmailStr = Field(description="Registered email address.")
    password: str = Field(
        min_length=1,
        max_length=PASSWORD_MAX_BYTES,
        description="Account password.",
    )

    @field_validator("email", mode="before")
    @classmethod
    def _normalise_email(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value


class ForgotPasswordRequest(BaseModel):
    email: EmailStr = Field(description="Account email to send reset instructions.")

    @field_validator("email", mode="before")
    @classmethod
    def _normalise_email(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=8, description="Password reset token.")
    new_password: str = Field(
        min_length=1,
        max_length=PASSWORD_MAX_BYTES,
        description="New password adhering to security policy.",
    )

    @field_validator("new_password")
    @classmethod
    def _check_policy(cls, value: str) -> str:
        return validate_password_policy(value)


class TokenResponse(BaseModel):
    """Issued access token plus the authenticated account."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Token lifetime in seconds.")
    user: UserResponse
