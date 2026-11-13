"""Product endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.core.dependencies import AdminUser, CurrentUser
from app.schemas.product import (
    PaginatedProducts,
    ProductCreate,
    ProductResponse,
    ProductUpdate,
)
from app.schemas.user import UserRole
from app.services import product_service
from app.services.product_service import (
    CatalogConflictError,
    ProductNotFoundError,
)

router = APIRouter()


@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product (admin only)",
    responses={409: {"description": "SKU already exists"}},
)
def create_product(payload: ProductCreate, current_user: AdminUser) -> ProductResponse:
    try:
        product = product_service.create_product(payload)
    except CatalogConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return ProductResponse.model_validate(product)


@router.get(
    "",
    response_model=PaginatedProducts,
    summary="List products",
)
def list_products(
    current_user: CurrentUser,
    is_active: bool | None = Query(default=None),
    q: str | None = Query(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[^,()\\]*$",
        description="Substring match on SKU or name.",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PaginatedProducts:
    """Customers only ever see active products; staff/admins see everything."""
    include_inactive = current_user["role"] != UserRole.customer.value
    items, total = product_service.list_products(
        include_inactive=include_inactive,
        is_active=is_active,
        query_text=q,
        limit=limit,
        offset=offset,
    )
    return PaginatedProducts(
        items=[ProductResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Get a product",
    responses={404: {"description": "Product not found (or inactive for customers)"}},
)
def get_product(product_id: UUID, current_user: CurrentUser) -> ProductResponse:
    include_inactive = current_user["role"] != UserRole.customer.value
    product = product_service.get_product(product_id, include_inactive=include_inactive)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found.")
    return ProductResponse.model_validate(product)


@router.patch(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Update a product (admin only)",
    responses={
        404: {"description": "Product not found"},
        409: {"description": "SKU conflict"},
    },
)
def update_product(
    product_id: UUID,
    payload: ProductUpdate,
    current_user: AdminUser,
) -> ProductResponse:
    try:
        product = product_service.update_product(product_id, payload)
    except ProductNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found.") from None
    except CatalogConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return ProductResponse.model_validate(product)


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a product (admin only)",
    responses={404: {"description": "Product not found"}},
)
def delete_product(product_id: UUID, current_user: AdminUser) -> Response:
    """Sets `is_active=false` and deactivates all variants and plans beneath it."""
    try:
        product_service.deactivate_product(product_id)
    except ProductNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found.") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
