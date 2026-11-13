"""Supabase client management.

A single client is created per process and reused. The client is thread-safe
(httpx under the hood), so it can be shared across FastAPI's worker threads.
"""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """Return the process-wide Supabase client.

    Raises immediately with an actionable message when configuration is
    missing, instead of failing later with an opaque network error.
    """
    settings = get_settings()

    if not settings.supabase_url or not settings.supabase_key:
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY in backend/.env (see .env.example)."
        )

    return create_client(settings.supabase_url, settings.supabase_key)


def reset_supabase_client() -> None:
    """Drop the cached client. Used by tests after swapping credentials."""
    get_supabase.cache_clear()
