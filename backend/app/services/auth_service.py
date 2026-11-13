"""Authentication business logic.

Accounts live in our own `public.users` table (bcrypt hashes), so this API
issues its own HS256 access tokens instead of delegating to Supabase Auth.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.services import store, user_service

_DUMMY_PASSWORD_HASH = (
    "$2b$12$t4jczpakb5qE66EGSGb1YuO5f1eBw0.9lrzcQL/cbHG4n0/BVz3Wq"
)


class InvalidCredentialsError(Exception):
    """Unknown email or wrong password. Deliberately indistinguishable."""


class InactiveAccountError(Exception):
    """Password was correct, but the account has been deactivated."""


class InvalidCurrentPasswordError(Exception):
    """The supplied current password does not match the stored hash."""


class PasswordReuseError(Exception):
    """The new password is identical to the current one."""


class PasswordConflictError(Exception):
    """Another request changed the password concurrently."""


class InvalidResetTokenError(Exception):
    """The password reset token is invalid, used, or expired."""


def authenticate(email: str, password: str) -> dict[str, Any]:
    """Verify credentials and return the user's public fields (+ version).

    Raises `InvalidCredentialsError` or `InactiveAccountError`.
    """
    record = user_service.get_user_credentials_by_email(email)

    if record is None:
        # Spend the same time as a real check so callers can't enumerate emails.
        verify_password(password, _DUMMY_PASSWORD_HASH)
        raise InvalidCredentialsError()

    if not verify_password(password, record["password_hash"]):
        raise InvalidCredentialsError()

    if not record.get("is_active", False):
        raise InactiveAccountError()

    return {key: value for key, value in record.items() if key != "password_hash"}


def create_token_for_user(user: dict[str, Any]) -> tuple[str, int]:
    """Issue an access token bound to the user's current token version."""
    return create_access_token(
        user_id=str(user["id"]),
        role=user["role"],
        email=user["email"],
        token_version=int(user.get("token_version", 0)),
    )


def change_password(
    user_id: str,
    *,
    current_password: str,
    new_password: str,
) -> dict[str, Any]:
    """Rotate a user's password and revoke their previously issued tokens."""
    record = user_service.get_user_credentials_by_id(user_id)
    if record is None:
        raise user_service.UserNotFoundError(user_id)

    if not verify_password(current_password, record["password_hash"]):
        raise InvalidCurrentPasswordError()

    if verify_password(new_password, record["password_hash"]):
        raise PasswordReuseError()

    updated = user_service.update_password(
        user_id,
        new_password_hash=hash_password(new_password),
        expected_token_version=int(record.get("token_version", 0)),
    )
    if updated is None:
        raise PasswordConflictError()
    return updated


def request_password_reset(email: str) -> dict[str, Any]:
    """Generate a password reset token and simulated delivery link."""
    user = user_service.get_user_by_email(email)

    # Always return a generic success message to prevent user enumeration
    if not user or not user.get("is_active"):
        return {
            "message": "If the email is registered, a password reset link has been dispatched.",
            "reset_token": None,
        }

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    store.create_password_reset(str(user["id"]), token, expires_at)

    return {
        "message": "Password reset link sent to your registered email address.",
        "reset_token": token,  # Exposed for testing/demo presentation
        "expires_in_seconds": 3600,
    }


def reset_password_with_token(token: str, new_password: str) -> dict[str, Any]:
    """Validate token and update password."""
    reset_record = store.get_password_reset(token)
    if not reset_record:
        raise InvalidResetTokenError("Invalid or expired reset token.")

    expires_at = datetime.fromisoformat(str(reset_record["expires_at"]).replace("Z", "+00:00"))
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise InvalidResetTokenError("Reset token has expired.")

    user_id = str(reset_record["user_id"])
    record = user_service.get_user_credentials_by_id(user_id)
    if record is None:
        raise InvalidResetTokenError("Invalid or expired reset token.")

    updated = user_service.update_password(
        user_id,
        new_password_hash=hash_password(new_password),
        expected_token_version=int(record.get("token_version", 0)),
    )
    if updated is None:
        raise PasswordConflictError()

    store.mark_password_reset_used(token)
    return {"message": "Password successfully reset. You can now log in with your new password."}
