"""Business logic and Supabase queries for plans (pricing)."""

from __future__ import annotations

from typing import Any

from postgrest.exceptions import APIError

from app.core.database import get_supabase
from app.core.db_errors import is_unique_violation
from app.schemas.plan import PlanCreate, PlanUpdate
from app.services import product_service

PLAN_COLUMNS = (
    "id,variant_id,name,billing_interval,interval_count,price_inr,currency,"
    "trial_days,is_active,created_at,updated_at"
)


class PlanNotFoundError(Exception):
    """No plan with that id."""


def _client():
    return get_supabase()


def get_plan_row(plan_id: Any) -> dict[str, Any] | None:
    response = (
        _client()
        .table("plans")
        .select(PLAN_COLUMNS)
        .eq("id", str(plan_id))
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def get_plan(plan_id: Any, *, include_inactive: bool) -> dict[str, Any] | None:
    row = get_plan_row(plan_id)
    if row is None:
        return None
    if not include_inactive and not row["is_active"]:
        return None
    return row


def list_plans(
    variant_id: Any,
    *,
    include_inactive: bool,
    is_active: bool | None = None,
    query_text: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    if product_service.get_variant_row(variant_id) is None:
        raise product_service.VariantNotFoundError(str(variant_id))

    query = (
        _client()
        .table("plans")
        .select(PLAN_COLUMNS, count="exact")
        .eq("variant_id", str(variant_id))
    )

    if not include_inactive:
        if is_active is False:
            return [], 0
        query = query.eq("is_active", True)
    elif is_active is not None:
        query = query.eq("is_active", is_active)

    if query_text:
        safe = " ".join(query_text.split())[:100]
        if safe:
            query = query.ilike("name", f"%{safe}%")

    # Cheapest first is the natural order for a pricing table.
    response = (
        query.order("price_inr", desc=False)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return response.data or [], int(response.count or 0)


def create_plan(payload: PlanCreate) -> dict[str, Any]:
    variant = product_service.get_variant_row(payload.variant_id)
    if variant is None:
        raise product_service.VariantNotFoundError(str(payload.variant_id))
    if not variant["is_active"]:
        raise product_service.CatalogConflictError(
            "Cannot add a plan to an inactive variant."
        )

    product = product_service.get_product_row(variant["product_id"])
    if product is None:
        raise product_service.ProductNotFoundError(str(variant["product_id"]))
    if not product["is_active"]:
        raise product_service.CatalogConflictError(
            "Cannot add a plan while the parent product is inactive."
        )

    if _plan_name_taken(variant["id"], payload.name):
        raise product_service.CatalogConflictError(
            "A plan with this name already exists for this variant."
        )

    row = {
        "variant_id": str(payload.variant_id),
        "name": payload.name,
        "billing_interval": payload.billing_interval.value,
        "interval_count": payload.interval_count,
        "price_inr": payload.price_inr,
        "trial_days": payload.trial_days,
    }

    try:
        response = (
            _client().table("plans").insert(row).select(PLAN_COLUMNS).execute()
        )
    except APIError as exc:
        if is_unique_violation(exc):
            raise product_service.CatalogConflictError(
                "A plan with this name already exists for this variant."
            ) from exc
        raise

    return response.data[0]


def update_plan(plan_id: Any, payload: PlanUpdate) -> dict[str, Any]:
    existing = get_plan_row(plan_id)
    if existing is None:
        raise PlanNotFoundError(str(plan_id))

    changes = payload.model_dump(exclude_unset=True)

    if changes.get("is_active") is True:
        variant = product_service.get_variant_row(existing["variant_id"])
        if variant is None:
            raise product_service.VariantNotFoundError(str(existing["variant_id"]))
        if not variant["is_active"]:
            raise product_service.CatalogConflictError(
                "Cannot activate a plan while its variant is inactive."
            )
        product = product_service.get_product_row(variant["product_id"])
        if product is None:
            raise product_service.ProductNotFoundError(str(variant["product_id"]))
        if not product["is_active"]:
            raise product_service.CatalogConflictError(
                "Cannot activate a plan while its product is inactive."
            )

    if changes.get("name") and changes["name"].casefold() != existing["name"].casefold():
        if _plan_name_taken(
            existing["variant_id"], changes["name"], exclude_id=existing["id"]
        ):
            raise product_service.CatalogConflictError(
                "A plan with this name already exists for this variant."
            )

    if "billing_interval" in changes:
        changes["billing_interval"] = changes["billing_interval"].value

    try:
        response = (
            _client()
            .table("plans")
            .update(changes)
            .eq("id", existing["id"])
            .select(PLAN_COLUMNS)
            .execute()
        )
    except APIError as exc:
        if is_unique_violation(exc):
            raise product_service.CatalogConflictError(
                "A plan with this name already exists for this variant."
            ) from exc
        raise

    return response.data[0]


def deactivate_plan(plan_id: Any) -> dict[str, Any]:
    existing = get_plan_row(plan_id)
    if existing is None:
        raise PlanNotFoundError(str(plan_id))

    response = (
        _client()
        .table("plans")
        .update({"is_active": False})
        .eq("id", existing["id"])
        .select(PLAN_COLUMNS)
        .execute()
    )
    return response.data[0]


def _plan_name_taken(
    variant_id: str, name: str, *, exclude_id: str | None = None
) -> bool:
    query = (
        _client()
        .table("plans")
        .select("id")
        .eq("variant_id", variant_id)
        .ilike("name", name)
    )
    if exclude_id:
        query = query.neq("id", exclude_id)
    return bool((query.limit(1).execute()).data)
