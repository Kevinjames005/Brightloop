"""Brightloop Subscription Management Platform - FastAPI entry point."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from postgrest.exceptions import APIError

from app.api.v1.api import api_router
from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(
    title=settings.project_name,
    version=settings.api_version,
    description=(
        "Backend for recurring subscriptions, automated billing and payments. "
        "All monetary amounts are integers in whole rupees."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Enable CORS for frontend web apps
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    """Friendly pointer for anyone who opens the API address in a browser."""
    return {"service": settings.project_name, "docs": "/docs", "health": "/health"}


@app.get("/health", tags=["Health"], summary="Liveness probe")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "service": settings.project_name,
        "version": settings.api_version,
        "supabase_configured": bool(
            settings.supabase_url and settings.supabase_key
        ),
        "auth_configured": bool(
            settings.jwt_secret and len(settings.jwt_secret) >= 32
        ),
    }


@app.exception_handler(APIError)
async def supabase_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """Never leak raw PostgREST/SQL details to API clients."""
    logger.error(
        "Supabase error on %s %s | code=%s | message=%s | details=%s",
        request.method,
        request.url.path,
        getattr(exc, "code", None),
        getattr(exc, "message", None),
        getattr(exc, "details", None),
    )

    raw = str(exc).lower()
    if "invalid api key" in raw or "error 401" in raw or "error 403" in raw:
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Database authentication failed. Check SUPABASE_URL and "
                    "SUPABASE_SERVICE_ROLE_KEY in backend/.env."
                )
            },
        )

    if getattr(exc, "code", None) in {"42P01", "42703", "PGRST204", "PGRST205"}:
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Database schema is out of date. Run the SQL files in "
                    "backend/sql in order (latest: 005_subscriptions_billing.sql)."
                )
            },
        )

    return JSONResponse(
        status_code=502,
        content={"detail": "The database rejected the request. Please try again."},
    )
