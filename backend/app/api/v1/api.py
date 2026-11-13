"""Version 1 API router: aggregates all endpoint routers."""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, billing, plans, products, users, variants

api_router = APIRouter()

api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["Auth"],
)

api_router.include_router(
    users.router,
    prefix="/users",
    tags=["Users"],
)

api_router.include_router(
    products.router,
    prefix="/products",
    tags=["Catalog: Products"],
)

api_router.include_router(
    variants.router,
    prefix="/variants",
    tags=["Catalog: Variants"],
)

api_router.include_router(
    plans.router,
    prefix="/plans",
    tags=["Catalog: Plans"],
)

api_router.include_router(
    billing.router,
    prefix="",
    tags=["Subscriptions & Billing"],
)
