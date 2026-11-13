"""Reusable FastAPI dependencies: authentication and role-based access."""

from __future__ import annotations

from typing import Annotated, Any, Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.core.config import get_settings
from app.core.security import TokenError, decode_access_token
from app.schemas.user import UserRole
from app.services import user_service

# Swagger's "Authorize" button posts the form to /auth/token.
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{get_settings().api_v1_prefix}/auth/token",
    auto_error=False,
)


def _unauthorized(detail: str = "Not authenticated.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> dict[str, Any]:
    """Resolve the bearer token to a live user.

    The database is the source of truth for `role` and `is_active`, so a role
    change or deactivation takes effect immediately - it does not wait for the
    token to expire.
    """
    if not token:
        raise _unauthorized()

    try:
        payload = decode_access_token(token)
    except TokenError:
        raise _unauthorized("Invalid or expired token.") from None

    user = user_service.get_user_by_id(payload["sub"])

    if user is None or not user.get("is_active", False):
        raise _unauthorized("This account is no longer active.")

    # Password changes bump token_version, revoking tokens issued before it.
    if int(payload.get("ver", 0)) != int(user.get("token_version", 0)):
        raise _unauthorized("Session expired. Please log in again.")

    return user


CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[..., dict[str, Any]]:
    """Dependency factory enforcing role-based access.

    Usage:
        @router.get("/reports")
        def reports(user: Annotated[dict, Depends(require_roles(UserRole.admin))]):
            ...
    """
    allowed = {role.value for role in roles}
    allowed_label = ", ".join(sorted(allowed))

    def dependency(current_user: CurrentUser) -> dict[str, Any]:
        if current_user.get("role") not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires one of these roles: {allowed_label}.",
            )
        return current_user

    return dependency


# Convenience guards for the common cases.
AdminUser = Annotated[dict[str, Any], Depends(require_roles(UserRole.admin))]
StaffUser = Annotated[
    dict[str, Any],
    Depends(require_roles(UserRole.admin, UserRole.staff)),
]
