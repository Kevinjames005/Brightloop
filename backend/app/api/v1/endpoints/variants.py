"""Product variant endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.core.dependencies import AdminUser, CurrentUser
from app.schemas.product import (
    PaginatedVariants,
    VariantCreate,
    VariantResponse,
    VariantUpdate,
)
from app.schemas.user import UserRole
from app.services import product_service
from app.services.product_service import (
    CatalogConflictError,
    ProductNotFoundError,
    VariantNotFoundError,
)

router = APIRouter()


@router.post(
    "",
    response_model=VariantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product variant (admin only)",
    responses={
        404: {"description": "Product not found"},
        409: {"description": "SKU/name conflict, or product is inactive"},
    },
)
def create_variant(payload: VariantCreate, current_user: AdminUser) -> VariantResponse:
    try:
        variant = product_service.create_variant(payload)
    except ProductNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found.") from None
    except CatalogConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return VariantResponse.model_validate(variant)


@router.get(
    "",
    response_model=PaginatedVariants,
    summary="List variants of a product",
    responses={404: {"description": "Product not found"}},
)
def list_variants(
    current_user: CurrentUser,
    product_id: UUID = Query(description="Owning product."),
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
) -> PaginatedVariants:
    include_inactive = current_user["role"] != UserRole.customer.value
    try:
        items, total = product_service.list_variants(
            product_id,
            include_inactive=include_inactive,
            is_active=is_active,
            query_text=q,
            limit=limit,
            offset=offset,
        )
    except ProductNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found.") from None
    return PaginatedVariants(
        items=[VariantResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{variant_id}",
    response_model=VariantResponse,
    summary="Get a variant",
    responses={404: {"description": "Variant not found (or inactive for customers)"}},
)
def get_variant(variant_id: UUID, current_user: CurrentUser) -> VariantResponse:
    include_inactive = current_user["role"] != UserRole.customer.value
    variant = product_service.get_variant(variant_id, include_inactive=include_inactive)
    if variant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Variant not found.")
    return VariantResponse.model_validate(variant)


@router.patch(
    "/{variant_id}",
    response_model=VariantResponse,
    summary="Update a variant (admin only)",
    responses={
        404: {"description": "Variant not found"},
        409: {"description": "SKU/name conflict, or parent product is inactive"},
    },
)
def update_variant(
    variant_id: UUID,
    payload: VariantUpdate,
    current_user: AdminUser,
) -> VariantResponse:
    try:
        variant = product_service.update_variant(variant_id, payload)
    except VariantNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Variant not found.") from None
    except (ProductNotFoundError, CatalogConflictError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return VariantResponse.model_validate(variant)


@router.delete(
    "/{variant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a variant (admin only)",
    responses={404: {"description": "Variant not found"}},
)
def delete_variant(variant_id: UUID, current_user: AdminUser) -> Response:
    """Sets `is_active=false` and deactivates the variant's plans."""
    try:
        product_service.deactivate_variant(variant_id)
    except VariantNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Variant not found.") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
