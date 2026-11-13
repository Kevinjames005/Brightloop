"""Authentication endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.schemas.user import UserResponse
from app.services import auth_service
from app.services.auth_service import (
    InactiveAccountError,
    InvalidCredentialsError,
    InvalidResetTokenError,
    PasswordConflictError,
)

router = APIRouter()


def _authenticate_or_raise(email: str, password: str) -> dict[str, Any]:
    try:
        return auth_service.authenticate(email, password)
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except InactiveAccountError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated. Contact an administrator.",
        ) from None


def _issue_token(user: dict[str, Any]) -> TokenResponse:
    token, expires_in = auth_service.create_token_for_user(user)
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in and receive an access token",
    responses={
        401: {"description": "Invalid email or password"},
        403: {"description": "Account deactivated"},
    },
)
def login(payload: LoginRequest) -> TokenResponse:
    """JSON login for the customer portal / staff dashboard."""
    return _issue_token(_authenticate_or_raise(payload.email, payload.password))


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="OAuth2 password form (Swagger 'Authorize' button)",
)
def login_for_docs(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> TokenResponse:
    """Form-encoded variant of /login.

    Exists so Swagger UI can obtain a token and attach it to protected routes.
    """
    return _issue_token(_authenticate_or_raise(form.username, form.password))


@router.post(
    "/forgot-password",
    summary="Request a password reset link",
)
def forgot_password(payload: ForgotPasswordRequest) -> dict[str, Any]:
    """Generates password reset token and simulated email delivery."""
    return auth_service.request_password_reset(payload.email)


@router.post(
    "/reset-password",
    summary="Reset password using reset token",
)
def reset_password(payload: ResetPasswordRequest) -> dict[str, Any]:
    """Validates reset token and sets a new password adhering to platform policy."""
    try:
        return auth_service.reset_password_with_token(payload.token, payload.new_password)
    except InvalidResetTokenError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    except PasswordConflictError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The password was changed by another request. Please try again.",
        ) from None
