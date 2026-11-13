"""Password hashing and access-token helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

# bcrypt truncates input at 72 bytes. We reject longer passwords in the schema
# instead of silently accepting a truncation collision.
BCRYPT_MAX_BYTES = 72

# HS256 keys shorter than the hash output add no security.
MIN_JWT_SECRET_LENGTH = 32

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,
)


def hash_password(password: str) -> str:
    """Hash a plaintext password. Returns the bcrypt digest."""
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError(
            f"Password must be at most {BCRYPT_MAX_BYTES} bytes (bcrypt limit)."
        )
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Constant-time check of a plaintext password against a stored hash."""
    try:
        return pwd_context.verify(plain_password, password_hash)
    except (ValueError, TypeError):
        # Malformed / unknown hash format -> treat as a failed login.
        return False


# --------------------------------------------------------------------------- #
# Access tokens
# --------------------------------------------------------------------------- #


class TokenError(Exception):
    """Raised when a token is missing claims, tampered with, or expired."""


def _jwt_settings() -> tuple[str, str, str, int]:
    settings = get_settings()
    if not settings.jwt_secret or len(settings.jwt_secret) < MIN_JWT_SECRET_LENGTH:
        raise RuntimeError(
            "JWT_SECRET is missing or too short (minimum "
            f"{MIN_JWT_SECRET_LENGTH} characters). Set it in backend/.env. "
            "Generate one with: python -c \"import secrets; "
            "print(secrets.token_urlsafe(48))\""
        )
    return (
        settings.jwt_secret,
        settings.jwt_algorithm,
        settings.jwt_issuer,
        settings.access_token_expire_minutes,
    )


def create_access_token(
    *,
    user_id: str,
    role: str,
    email: str,
    token_version: int = 0,
    expires_delta: timedelta | None = None,
) -> tuple[str, int]:
    """Sign a short-lived access token.

    `token_version` is embedded as the `ver` claim so password changes can
    revoke tokens that were issued before the change.

    Returns `(token, expires_in_seconds)`.
    """
    secret, algorithm, issuer, ttl_minutes = _jwt_settings()

    now = datetime.now(timezone.utc)
    expires_at = now + (expires_delta or timedelta(minutes=ttl_minutes))

    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "email": email,
        "ver": int(token_version),
        "type": "access",
        "iss": issuer,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }

    token = jwt.encode(payload, secret, algorithm=algorithm)
    return token, int((expires_at - now).total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify signature/expiry/issuer and return the claims.

    Raises `TokenError` for anything untrusted. Never leaks library details.
    """
    secret, algorithm, issuer, _ = _jwt_settings()

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[algorithm],
            issuer=issuer,
            options={"require_exp": True, "require_sub": True},
        )
    except JWTError as exc:
        raise TokenError("Invalid or expired token.") from exc

    if payload.get("type") != "access":
        raise TokenError("Invalid token type.")

    if not isinstance(payload.get("sub"), str) or not payload["sub"]:
        raise TokenError("Token is missing a subject.")

    return payload
