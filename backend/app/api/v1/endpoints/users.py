"""User endpoints: registration, profile, and admin account management."""

from __future__ import annotations

import logging
import secrets
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, status

from app.core.config import get_settings
from app.core.dependencies import AdminUser, CurrentUser
from app.schemas.auth import TokenResponse
from app.schemas.user import (
    PaginatedUsers,
    PasswordChange,
    UserRegister,
    UserResponse,
    UserRole,
    UserRoleUpdate,
)
from app.services import auth_service, user_service
from app.services.auth_service import (
    InvalidCurrentPasswordError,
    PasswordConflictError,
    PasswordReuseError,
)
from app.services.user_service import (
    EmailAlreadyRegisteredError,
    UserNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _authorise_role_assignment(
    requested_role: UserRole,
    bootstrap_token: str | None,
) -> None:
    """Anonymous callers may only self-register as 'customer'.

    'admin' / 'staff' accounts require the bootstrap secret, so the public
    endpoint cannot be used for privilege escalation.
    """
    if requested_role is UserRole.customer:
        return

    expected = get_settings().bootstrap_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Self-registration is limited to the 'customer' role. "
                "Ask an administrator to create this account."
            ),
        )

    # Compare as bytes: compare_digest rejects non-ASCII str inputs.
    if not bootstrap_token or not secrets.compare_digest(
        bootstrap_token.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing X-Bootstrap-Token for this role.",
        )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    responses={
        409: {"description": "Email is already registered"},
        403: {"description": "Role requires a valid bootstrap token"},
    },
)
def register_user(
    payload: UserRegister,
    x_bootstrap_token: str | None = Header(
        default=None,
        description="Required only when role is 'admin' or 'staff'.",
        alias="X-Bootstrap-Token",
    ),
) -> UserResponse:
    _authorise_role_assignment(payload.role, x_bootstrap_token)

    try:
        user = user_service.create_user(payload)
    except EmailAlreadyRegisteredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from None

    return UserResponse.model_validate(user)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get the authenticated user's profile",
)
def read_current_user(current_user: CurrentUser) -> UserResponse:
    """Any authenticated role (admin, staff, customer) can call this."""
    return UserResponse.model_validate(current_user)


@router.post(
    "/me/change-password",
    response_model=TokenResponse,
    summary="Change your password",
    responses={
        400: {"description": "Current password is wrong, or new password reused"},
        401: {"description": "Not authenticated"},
        409: {"description": "Concurrent password change"},
    },
)
def change_own_password(
    payload: PasswordChange,
    current_user: CurrentUser,
) -> TokenResponse:
    """Rotate the password and return a fresh token.

    All previously issued tokens are revoked (`token_version` is bumped), so the
    caller must replace its stored token with the one returned here.
    """
    try:
        updated = auth_service.change_password(
            str(current_user["id"]),
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except InvalidCurrentPasswordError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        ) from None
    except PasswordReuseError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from the current password.",
        ) from None
    except PasswordConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Password was changed by another request. Please retry.",
        ) from None
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        ) from None

    logger.info("password_changed user_id=%s", current_user["id"])

    token, expires_in = auth_service.create_token_for_user(updated)
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserResponse.model_validate(updated),
    )


@router.get(
    "",
    response_model=PaginatedUsers,
    summary="List users (admin only)",
    responses={403: {"description": "Admin role required"}},
)
def list_users(
    current_user: AdminUser,
    role: UserRole | None = Query(default=None, description="Filter by role."),
    is_active: bool | None = Query(
        default=None, description="Filter by activation status."
    ),
    q: str | None = Query(
        default=None,
        min_length=1,
        max_length=100,
        # Reserved by PostgREST's filter grammar; reject instead of silently
        # mangling the search term.
        pattern=r"^[^,()\\]*$",
        description=(
            "Case-insensitive substring match on email or name. "
            "Commas, parentheses and backslashes are not supported."
        ),
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PaginatedUsers:
    """Paginated directory, newest first, with filters and a total count."""
    items, total = user_service.list_users(
        limit=limit,
        offset=offset,
        role=role,
        is_active=is_active,
        query_text=q,
    )
    return PaginatedUsers(
        items=[UserResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch(
    "/{user_id}/role",
    response_model=UserResponse,
    summary="Change a user's role (admin only)",
    responses={
        403: {"description": "Admin role required"},
        404: {"description": "User not found"},
        409: {"description": "Admins cannot change their own role"},
    },
)
def change_user_role(
    user_id: UUID,
    payload: UserRoleUpdate,
    current_user: AdminUser,
) -> UserResponse:
    # Prevents accidental self-lockout; another admin must perform the change.
    if str(user_id) == str(current_user["id"]):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot change your own role. Ask another admin.",
        )

    try:
        updated = user_service.update_user_role(user_id, payload.role)
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        ) from None

    logger.info(
        "role_changed actor_id=%s target_id=%s new_role=%s",
        current_user["id"],
        user_id,
        payload.role.value,
    )
    return UserResponse.model_validate(updated)


def _set_activation(
    user_id: UUID,
    *,
    is_active: bool,
    actor: dict[str, Any],
) -> UserResponse:
    if not is_active and str(user_id) == str(actor["id"]):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot deactivate your own account.",
        )

    try:
        updated = user_service.set_user_active(user_id, is_active)
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        ) from None

    logger.info(
        "account_%s actor_id=%s target_id=%s",
        "activated" if is_active else "deactivated",
        actor["id"],
        user_id,
    )
    return UserResponse.model_validate(updated)


@router.post(
    "/{user_id}/deactivate",
    response_model=UserResponse,
    summary="Deactivate an account (admin only)",
    responses={
        403: {"description": "Admin role required"},
        404: {"description": "User not found"},
        409: {"description": "Admins cannot deactivate themselves"},
    },
)
def deactivate_user(user_id: UUID, current_user: AdminUser) -> UserResponse:
    """Existing tokens stop working immediately (is_active is checked per request)."""
    return _set_activation(user_id, is_active=False, actor=current_user)


@router.post(
    "/{user_id}/activate",
    response_model=UserResponse,
    summary="Reactivate an account (admin only)",
    responses={
        403: {"description": "Admin role required"},
        404: {"description": "User not found"},
    },
)
def activate_user(user_id: UUID, current_user: AdminUser) -> UserResponse:
    return _set_activation(user_id, is_active=True, actor=current_user)
