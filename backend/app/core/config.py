"""Application configuration, loaded from environment variables / .env.

Secrets (Supabase keys, bootstrap token) must never be hard-coded. Only the
backend holds the Supabase *service role* key, because password hashes live in
the `users` table.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# backend/ (config.py -> core -> app -> backend)
BASE_DIR = Path(__file__).resolve().parents[2]

# Local development convenience. Real deployments should inject env vars.
load_dotenv(BASE_DIR / ".env")


def _env(*names: str, default: str | None = None) -> str | None:
    """Return the first non-empty environment variable from `names`."""
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return default


def _env_int(name: str, default: int) -> int:
    """Read an integer env var, falling back to `default` when unset/invalid."""
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    project_name: str
    api_version: str
    api_v1_prefix: str

    # Supabase project settings.
    supabase_url: str | None
    # Service role key: bypasses Row Level Security, so it must stay server-side.
    supabase_key: str | None

    # Optional shared secret that allows creating 'admin' / 'staff' accounts
    # through the public /register endpoint. Leave unset to disable.
    bootstrap_token: str | None

    # Access tokens are signed by this API (accounts live in our own `users`
    # table, not Supabase Auth).
    jwt_secret: str | None
    jwt_algorithm: str
    jwt_issuer: str
    access_token_expire_minutes: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        project_name="Brightloop Subscription Management Platform",
        api_version="0.1.0",
        api_v1_prefix="/api/v1",
        supabase_url=_env("SUPABASE_URL"),
        # Accept a few common names so the .env is forgiving.
        supabase_key=_env(
            "SUPABASE_SERVICE_ROLE_KEY",
            "SUPABASE_SERVICE_KEY",
            "SUPABASE_KEY",
        ),
        bootstrap_token=_env("BOOTSTRAP_TOKEN"),
        jwt_secret=_env("JWT_SECRET", "JWT_SECRET_KEY", "SECRET_KEY"),
        jwt_algorithm=_env("JWT_ALGORITHM", default="HS256") or "HS256",
        jwt_issuer=_env("JWT_ISSUER", default="brightloop-api") or "brightloop-api",
        access_token_expire_minutes=_env_int("ACCESS_TOKEN_EXPIRE_MINUTES", 60),
    )


# Convenient module-level handle; use get_settings() when you need a fresh read
# (e.g. in tests that monkeypatch the environment).
settings = get_settings()
