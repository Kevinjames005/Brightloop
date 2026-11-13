"""Shared PostgreSQL error classification for Supabase/PostgREST calls."""

from __future__ import annotations

from postgrest.exceptions import APIError

# SQLSTATE codes.
UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"
NOT_NULL_VIOLATION = "23502"


def _haystack(error: APIError) -> str:
    return " ".join(
        str(part)
        for part in (
            getattr(error, "code", None),
            getattr(error, "message", None),
            getattr(error, "details", None),
            getattr(error, "hint", None),
        )
        if part
    ).lower()


def is_unique_violation(error: APIError) -> bool:
    return UNIQUE_VIOLATION in _haystack(error) or "duplicate key" in _haystack(error)


def is_foreign_key_violation(error: APIError) -> bool:
    haystack = _haystack(error)
    return FOREIGN_KEY_VIOLATION in haystack or "foreign key" in haystack
