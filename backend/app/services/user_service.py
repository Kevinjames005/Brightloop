"""Business logic and Supabase queries for users."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from postgrest.exceptions import APIError
from supabase import Client

from app.core.database import get_supabase
from app.core.db_errors import is_unique_violation
from app.core.security import hash_password
from app.schemas.user import UserRegister, UserRole

# Selecting explicit columns guarantees `password_hash` never leaves the DB.
PUBLIC_USER_COLUMNS = "id,email,name,role,is_active,created_at,updated_at"

# Internal columns needed to authenticate a request. `token_version` is never
# serialised: UserResponse ignores unknown fields.
AUTH_USER_COLUMNS = f"{PUBLIC_USER_COLUMNS},token_version"


class EmailAlreadyRegisteredError(Exception):
    """Raised when the email is already taken."""


class UserServiceError(Exception):
    """Raised when Supabase returns an unusable response."""


class UserNotFoundError(Exception):
    """Raised when the target user does not exist."""


class ConcurrentUpdateError(Exception):
    """Raised when a row changed between read and write."""


def _client() -> Client:
    return get_supabase()


def _normalise_email(email: str) -> str:
    return email.strip().lower()


def _normalise_id(user_id: str | UUID) -> str | None:
    try:
        return str(UUID(str(user_id)))
    except (ValueError, AttributeError, TypeError):
        return None


def _is_unique_violation(error: APIError) -> bool:
    return is_unique_violation(error)

def get_user_by_email(email: str) -> dict[str, Any] | None:
    """Look up a user by email (case-insensitive). Returns public fields only."""
    norm = _normalise_email(email)
    response = (
        _client()
        .table("users")
        .select(PUBLIC_USER_COLUMNS)
        .eq("email", norm)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def create_user(payload: UserRegister) -> dict[str, Any]:
    """Hash the password and insert the user.

    The unique index on `users.email` is the source of truth: the pre-check is
    only a fast path, and a concurrent insert is still caught via unique violations.
    """
    email = _normalise_email(payload.email)

    if get_user_by_email(email) is not None:
        raise EmailAlreadyRegisteredError(email)

    pwd_hash = hash_password(payload.password)
    row = {
        "email": email,
        "password_hash": pwd_hash,
        "name": payload.name,
        "role": payload.role.value,
    }

    try:
        response = (
            _client()
            .table("users")
            .insert(row)
            .select(PUBLIC_USER_COLUMNS)
            .execute()
        )
    except APIError as exc:
        if _is_unique_violation(exc):
            raise EmailAlreadyRegisteredError(email) from exc
        raise

    rows = response.data or []
    if not rows:
        raise UserServiceError("Supabase returned no row after inserting the user.")
    return rows[0]


def get_user_by_id(user_id: str | UUID) -> dict[str, Any] | None:
    """Fetch a user by id, including `token_version` for auth checks."""
    normalised_id = _normalise_id(user_id)
    if normalised_id is None:
        return None

    response = (
        _client()
        .table("users")
        .select(AUTH_USER_COLUMNS)
        .eq("id", normalised_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def get_user_credentials_by_email(email: str) -> dict[str, Any] | None:
    """INTERNAL USE ONLY: returns the row including `password_hash`.

    Used solely by the login flow to verify the password. Never serialise or
    log the result of this function.
    """
    norm = _normalise_email(email)
    response = (
        _client()
        .table("users")
        .select(f"{AUTH_USER_COLUMNS},password_hash")
        .eq("email", norm)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def get_user_credentials_by_id(user_id: str | UUID) -> dict[str, Any] | None:
    """INTERNAL USE ONLY: credentials row for the password-change flow."""
    normalised_id = _normalise_id(user_id)
    if normalised_id is None:
        return None

    response = (
        _client()
        .table("users")
        .select(f"{AUTH_USER_COLUMNS},password_hash")
        .eq("id", normalised_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def update_user_role(user_id: str | UUID, role: UserRole) -> dict[str, Any]:
    """Set a user's role. Raises `UserNotFoundError` when no row matches."""
    normalised_id = _normalise_id(user_id)
    if normalised_id is None:
        raise UserNotFoundError(str(user_id))

    response = (
        _client()
        .table("users")
        .update({"role": role.value})
        .eq("id", normalised_id)
        .select(PUBLIC_USER_COLUMNS)
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise UserNotFoundError(str(user_id))
    return rows[0]


def set_user_active(user_id: str | UUID, is_active: bool) -> dict[str, Any]:
    """Activate / deactivate a user. Raises `UserNotFoundError` if missing."""
    normalised_id = _normalise_id(user_id)
    if normalised_id is None:
        raise UserNotFoundError(str(user_id))

    response = (
        _client()
        .table("users")
        .update({"is_active": is_active})
        .eq("id", normalised_id)
        .select(PUBLIC_USER_COLUMNS)
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise UserNotFoundError(str(user_id))
    return rows[0]


def update_password(
    user_id: str | UUID,
    *,
    new_password_hash: str,
    expected_token_version: int,
) -> dict[str, Any] | None:
    """Swap the password and bump `token_version`, revoking older tokens.

    The `token_version` filter makes this optimistically concurrent: if another
    request already changed the password, no row matches and `None` is returned.
    """
    normalised_id = _normalise_id(user_id)
    if normalised_id is None:
        return None

    response = (
        _client()
        .table("users")
        .update(
            {
                "password_hash": new_password_hash,
                "token_version": expected_token_version + 1,
            }
        )
        .eq("id", normalised_id)
        .eq("token_version", expected_token_version)
        .select(AUTH_USER_COLUMNS)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def _normalise_search(query_text: str) -> str:
    """Collapse whitespace; unsafe characters are rejected by the endpoint."""
    return " ".join(query_text.split())[:100]


def list_users(
    *,
    limit: int = 20,
    offset: int = 0,
    role: UserRole | None = None,
    is_active: bool | None = None,
    query_text: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Paginated user directory (newest first).

    Returns `(items, total_matching_before_pagination)`.
    """
    query = _client().table("users").select(PUBLIC_USER_COLUMNS, count="exact")

    if role is not None:
        query = query.eq("role", role.value)
    if is_active is not None:
        query = query.eq("is_active", is_active)

    if query_text:
        safe = _normalise_search(query_text)
        if safe:
            # `%` and `_` act as SQL LIKE wildcards inside the search term.
            query = query.or_(f"email.ilike.%{safe}%,name.ilike.%{safe}%")

    response = (
        query.order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return response.data or [], int(response.count or 0)
