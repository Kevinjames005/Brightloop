"""Pydantic schemas for the Users module."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# --------------------------------------------------------------------------- #
# Constants / password policy
# --------------------------------------------------------------------------- #

# "Longer than 8 characters" -> at least 9.
PASSWORD_MIN_LENGTH = 9
# bcrypt's hard limit, in bytes (not characters).
PASSWORD_MAX_BYTES = 72

# A "special character" is any non-alphanumeric character, excluding
# whitespace (a space should not satisfy the special-character rule).
PASSWORD_POLICY_REGEX = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*[^A-Za-z0-9\s])\S{9,72}$"

_UPPERCASE_RE = re.compile(r"[A-Z]")
_LOWERCASE_RE = re.compile(r"[a-z]")
_SPECIAL_RE = re.compile(r"[^A-Za-z0-9\s]")
_WHITESPACE_RE = re.compile(r"\s")


class UserRole(str, Enum):
    """The three roles supported by the platform."""

    admin = "admin"
    staff = "staff"
    customer = "customer"


def validate_password_policy(value: str) -> str:
    """Enforce the platform password policy, with one clear error per failure.

    Rules: > 8 characters, at least one uppercase letter, one lowercase letter,
    one special character, no whitespace, and <= 72 bytes for bcrypt.
    """
    if len(value) < PASSWORD_MIN_LENGTH:
        raise ValueError(
            f"Password must be longer than 8 characters "
            f"(minimum {PASSWORD_MIN_LENGTH})."
        )

    if len(value.encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise ValueError(
            f"Password must be at most {PASSWORD_MAX_BYTES} bytes long."
        )

    if _WHITESPACE_RE.search(value):
        raise ValueError("Password must not contain spaces or whitespace.")

    missing: list[str] = []
    if not _UPPERCASE_RE.search(value):
        missing.append("an uppercase letter")
    if not _LOWERCASE_RE.search(value):
        missing.append("a lowercase letter")
    if not _SPECIAL_RE.search(value):
        missing.append("a special character (e.g. ! @ # $ % & *)")

    if missing:
        raise ValueError("Password must contain " + ", ".join(missing) + ".")

    return value


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #


class UserRegister(BaseModel):
    """Payload for POST /api/v1/users/register."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "arjun@brightloop.in",
                "password": "Bright@2026",
                "name": "Arjun Nair",
                "role": "customer",
            }
        }
    )

    email: EmailStr = Field(
        description="Login email. Stored lowercase; must be unique.",
    )
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_BYTES,
        description=(
            "Longer than 8 characters, with at least one uppercase letter, "
            "one lowercase letter and one special character. Never stored in "
            "plaintext."
        ),
    )
    name: str = Field(
        min_length=2,
        max_length=120,
        description="Display name of the person.",
    )
    role: UserRole = Field(
        default=UserRole.customer,
        description=(
            "Default is 'customer'. Creating 'admin' or 'staff' accounts "
            "requires the X-Bootstrap-Token header."
        ),
    )

    @field_validator("email", mode="before")
    @classmethod
    def _normalise_email(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("name", mode="before")
    @classmethod
    def _clean_name(cls, value: object) -> object:
        if isinstance(value, str):
            # Collapse internal runs of whitespace, trim ends.
            return " ".join(value.split())
        return value

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return validate_password_policy(value)


class UserResponse(BaseModel):
    """Public representation of a user. Never includes `password_hash`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserRoleUpdate(BaseModel):
    """Payload for PATCH /api/v1/users/{user_id}/role."""

    model_config = ConfigDict(json_schema_extra={"example": {"role": "staff"}})

    role: UserRole


class PasswordChange(BaseModel):
    """Payload for POST /api/v1/users/me/change-password."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "current_password": "Bright@2026",
                "new_password": "Brighter@2027",
            }
        }
    )

    current_password: str = Field(
        min_length=1,
        max_length=PASSWORD_MAX_BYTES,
        description="Existing password, verified before the change.",
    )
    new_password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_BYTES,
        description=(
            "Must satisfy the same policy as registration and differ from the "
            "current password."
        ),
    )

    @field_validator("new_password")
    @classmethod
    def _check_new_password(cls, value: str) -> str:
        return validate_password_policy(value)


class PaginatedUsers(BaseModel):
    """Envelope for the admin user directory."""

    items: list[UserResponse]
    total: int = Field(description="Total matching users, before pagination.")
    limit: int
    offset: int
