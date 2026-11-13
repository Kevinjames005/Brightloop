"""Plan (pricing) endpoints. All monetary values are whole rupees."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.core.dependencies import AdminUser, CurrentUser
from app.schemas.plan import (
    PaginatedPlans,
    PlanCreate,
    PlanResponse,
    PlanUpdate,
)
from app.schemas.user import UserRole
from app.services import plan_service, product_service
from app.services.plan_service import PlanNotFoundError
from app.services.product_service import (
    CatalogConflictError,
    ProductNotFoundError,
    VariantNotFoundError,
)

router = APIRouter()


@router.post(
    "",
    response_model=PlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a plan (admin only)",
    responses={
        404: {"description": "Variant not found"},
        409: {"description": "Name conflict, or parent variant/product is inactive"},
    },
)
def create_plan(payload: PlanCreate, current_user: AdminUser) -> PlanResponse:
    try:
        plan = plan_service.create_plan(payload)
    except VariantNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Variant not found.") from None
    except ProductNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found.") from None
    except CatalogConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return PlanResponse.model_validate(plan)


@router.get(
    "",
    response_model=PaginatedPlans,
    summary="List plans of a variant",
    responses={404: {"description": "Variant not found"}},
)
def list_plans(
    current_user: CurrentUser,
    variant_id: UUID = Query(description="Owning variant."),
    is_active: bool | None = Query(default=None),
    q: str | None = Query(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[^,()\\]*$",
        description="Substring match on plan name.",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PaginatedPlans:
    include_inactive = current_user["role"] != UserRole.customer.value
    try:
        items, total = plan_service.list_plans(
            variant_id,
            include_inactive=include_inactive,
            is_active=is_active,
            query_text=q,
            limit=limit,
            offset=offset,
        )
    except VariantNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Variant not found.") from None
    return PaginatedPlans(
        items=[PlanResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{plan_id}",
    response_model=PlanResponse,
    summary="Get a plan",
    responses={404: {"description": "Plan not found (or inactive for customers)"}},
)
def get_plan(plan_id: UUID, current_user: CurrentUser) -> PlanResponse:
    include_inactive = current_user["role"] != UserRole.customer.value
    plan = plan_service.get_plan(plan_id, include_inactive=include_inactive)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found.")
    return PlanResponse.model_validate(plan)


@router.patch(
    "/{plan_id}",
    response_model=PlanResponse,
    summary="Update a plan (admin only)",
    responses={
        404: {"description": "Plan not found"},
        409: {"description": "Name conflict, or parent variant/product is inactive"},
    },
)
def update_plan(
    plan_id: UUID,
    payload: PlanUpdate,
    current_user: AdminUser,
) -> PlanResponse:
    try:
        plan = plan_service.update_plan(plan_id, payload)
    except PlanNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found.") from None
    except (VariantNotFoundError, ProductNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except CatalogConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return PlanResponse.model_validate(plan)


@router.delete(
    "/{plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a plan (admin only)",
    responses={404: {"description": "Plan not found"}},
)
def delete_plan(plan_id: UUID, current_user: AdminUser) -> Response:
    """Sets `is_active=false`. Existing subscriptions keep their price snapshot."""
    try:
        plan_service.deactivate_plan(plan_id)
    except PlanNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found.") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
