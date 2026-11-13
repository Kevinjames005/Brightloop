"""Business logic and Supabase queries for products and variants."""

from __future__ import annotations

from typing import Any

from postgrest.exceptions import APIError

from app.core.database import get_supabase
from app.core.db_errors import is_unique_violation
from app.schemas.product import ProductCreate, ProductUpdate, VariantCreate, VariantUpdate

PRODUCT_COLUMNS = "id,sku,name,description,is_active,created_at,updated_at"
VARIANT_COLUMNS = "id,product_id,sku,name,description,is_active,created_at,updated_at"


class ProductNotFoundError(Exception):
    """No product with that id."""


class VariantNotFoundError(Exception):
    """No variant with that id."""


class CatalogConflictError(Exception):
    """Duplicate SKU/name, or a state transition that would break the tree."""


def _client():
    return get_supabase()


def _search_term(query_text: str) -> str:
    return " ".join(query_text.split())[:100]


# --------------------------------------------------------------------------- #
# Products
# --------------------------------------------------------------------------- #


def get_product_row(product_id: Any) -> dict[str, Any] | None:
    """Fetch a product regardless of its active state."""
    response = (
        _client()
        .table("products")
        .select(PRODUCT_COLUMNS)
        .eq("id", str(product_id))
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def get_product(product_id: Any, *, include_inactive: bool) -> dict[str, Any] | None:
    """Public lookup. Inactive products are invisible to customers."""
    row = get_product_row(product_id)
    if row is None:
        return None
    if not include_inactive and not row["is_active"]:
        return None
    return row


def list_products(
    *,
    include_inactive: bool,
    is_active: bool | None = None,
    query_text: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    query = _client().table("products").select(PRODUCT_COLUMNS, count="exact")

    if not include_inactive:
        if is_active is False:
            return [], 0
        query = query.eq("is_active", True)
    elif is_active is not None:
        query = query.eq("is_active", is_active)

    if query_text:
        safe = _search_term(query_text)
        if safe:
            query = query.or_(f"sku.ilike.%{safe}%,name.ilike.%{safe}%")

    response = (
        query.order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return response.data or [], int(response.count or 0)


def create_product(payload: ProductCreate) -> dict[str, Any]:
    sku = payload.sku  # already normalised to uppercase by the schema

    if _sku_taken("products", sku):
        raise CatalogConflictError("A product with this SKU already exists.")

    row = {
        "sku": sku,
        "name": payload.name,
        "description": payload.description,
    }

    try:
        response = (
            _client().table("products").insert(row).select(PRODUCT_COLUMNS).execute()
        )
    except APIError as exc:
        if is_unique_violation(exc):
            raise CatalogConflictError("A product with this SKU already exists.") from exc
        raise

    return response.data[0]


def update_product(product_id: Any, payload: ProductUpdate) -> dict[str, Any]:
    existing = get_product_row(product_id)
    if existing is None:
        raise ProductNotFoundError(str(product_id))

    changes = payload.model_dump(exclude_unset=True)

    if changes.get("sku") and changes["sku"] != existing["sku"]:
        if _sku_taken("products", changes["sku"], exclude_id=existing["id"]):
            raise CatalogConflictError("A product with this SKU already exists.")

    # Cascade first: if this partially fails the product stays visible rather
    # than becoming an invisible parent of visible children.
    if changes.get("is_active") is False:
        _cascade_deactivate_product(existing["id"])

    try:
        response = (
            _client()
            .table("products")
            .update(changes)
            .eq("id", existing["id"])
            .select(PRODUCT_COLUMNS)
            .execute()
        )
    except APIError as exc:
        if is_unique_violation(exc):
            raise CatalogConflictError("A product with this SKU already exists.") from exc
        raise

    return response.data[0]


def deactivate_product(product_id: Any) -> dict[str, Any]:
    """Soft-delete a product and deactivate its whole subtree."""
    existing = get_product_row(product_id)
    if existing is None:
        raise ProductNotFoundError(str(product_id))

    _cascade_deactivate_product(existing["id"])

    response = (
        _client()
        .table("products")
        .update({"is_active": False})
        .eq("id", existing["id"])
        .select(PRODUCT_COLUMNS)
        .execute()
    )
    return response.data[0]


def _cascade_deactivate_product(product_id: str) -> None:
    variants = (
        _client()
        .table("product_variants")
        .select("id")
        .eq("product_id", product_id)
        .execute()
    ).data or []
    variant_ids = [row["id"] for row in variants]

    if variant_ids:
        (
            _client()
            .table("plans")
            .update({"is_active": False})
            .in_("variant_id", variant_ids)
            .execute()
        )

    (
        _client()
        .table("product_variants")
        .update({"is_active": False})
        .eq("product_id", product_id)
        .execute()
    )


# --------------------------------------------------------------------------- #
# Variants
# --------------------------------------------------------------------------- #


def get_variant_row(variant_id: Any) -> dict[str, Any] | None:
    """Fetch a variant regardless of its active state (used by plans too)."""
    response = (
        _client()
        .table("product_variants")
        .select(VARIANT_COLUMNS)
        .eq("id", str(variant_id))
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def get_variant(variant_id: Any, *, include_inactive: bool) -> dict[str, Any] | None:
    row = get_variant_row(variant_id)
    if row is None:
        return None
    if not include_inactive and not row["is_active"]:
        return None
    return row


def list_variants(
    product_id: Any,
    *,
    include_inactive: bool,
    is_active: bool | None = None,
    query_text: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    if get_product_row(product_id) is None:
        raise ProductNotFoundError(str(product_id))

    query = (
        _client()
        .table("product_variants")
        .select(VARIANT_COLUMNS, count="exact")
        .eq("product_id", str(product_id))
    )

    if not include_inactive:
        if is_active is False:
            return [], 0
        query = query.eq("is_active", True)
    elif is_active is not None:
        query = query.eq("is_active", is_active)

    if query_text:
        safe = _search_term(query_text)
        if safe:
            query = query.or_(f"sku.ilike.%{safe}%,name.ilike.%{safe}%")

    response = (
        query.order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return response.data or [], int(response.count or 0)


def create_variant(payload: VariantCreate) -> dict[str, Any]:
    product = get_product_row(payload.product_id)
    if product is None:
        raise ProductNotFoundError(str(payload.product_id))
    if not product["is_active"]:
        raise CatalogConflictError("Cannot add a variant to an inactive product.")

    if _sku_taken("product_variants", payload.sku):
        raise CatalogConflictError("A variant with this SKU already exists.")
    if _variant_name_taken(str(payload.product_id), payload.name):
        raise CatalogConflictError(
            "A variant with this name already exists for this product."
        )

    row = {
        "product_id": str(payload.product_id),
        "sku": payload.sku,
        "name": payload.name,
        "description": payload.description,
    }

    try:
        response = (
            _client()
            .table("product_variants")
            .insert(row)
            .select(VARIANT_COLUMNS)
            .execute()
        )
    except APIError as exc:
        if is_unique_violation(exc):
            raise CatalogConflictError(
                "A variant with this SKU or name already exists for this product."
            ) from exc
        raise

    return response.data[0]


def update_variant(variant_id: Any, payload: VariantUpdate) -> dict[str, Any]:
    existing = get_variant_row(variant_id)
    if existing is None:
        raise VariantNotFoundError(str(variant_id))

    changes = payload.model_dump(exclude_unset=True)

    if changes.get("is_active") is True:
        product = get_product_row(existing["product_id"])
        if product is None:
            raise ProductNotFoundError(str(existing["product_id"]))
        if not product["is_active"]:
            raise CatalogConflictError(
                "Cannot activate a variant while its product is inactive."
            )

    if changes.get("sku") and changes["sku"] != existing["sku"]:
        if _sku_taken("product_variants", changes["sku"], exclude_id=existing["id"]):
            raise CatalogConflictError("A variant with this SKU already exists.")

    if changes.get("name") and changes["name"].casefold() != existing["name"].casefold():
        if _variant_name_taken(
            existing["product_id"], changes["name"], exclude_id=existing["id"]
        ):
            raise CatalogConflictError(
                "A variant with this name already exists for this product."
            )

    try:
        response = (
            _client()
            .table("product_variants")
            .update(changes)
            .eq("id", existing["id"])
            .select(VARIANT_COLUMNS)
            .execute()
        )
    except APIError as exc:
        if is_unique_violation(exc):
            raise CatalogConflictError(
                "A variant with this SKU or name already exists for this product."
            ) from exc
        raise

    return response.data[0]


def deactivate_variant(variant_id: Any) -> dict[str, Any]:
    """Soft-delete a variant and deactivate its plans."""
    existing = get_variant_row(variant_id)
    if existing is None:
        raise VariantNotFoundError(str(variant_id))

    (
        _client()
        .table("plans")
        .update({"is_active": False})
        .eq("variant_id", existing["id"])
        .execute()
    )

    response = (
        _client()
        .table("product_variants")
        .update({"is_active": False})
        .eq("id", existing["id"])
        .select(VARIANT_COLUMNS)
        .execute()
    )
    return response.data[0]


# --------------------------------------------------------------------------- #
# Uniqueness helpers (fast, friendly errors; the DB index is the real guard)
# --------------------------------------------------------------------------- #


def _sku_taken(table: str, sku: str, *, exclude_id: str | None = None) -> bool:
    query = _client().table(table).select("id").eq("sku", sku)
    if exclude_id:
        query = query.neq("id", exclude_id)
    return bool((query.limit(1).execute()).data)


def _variant_name_taken(
    product_id: str, name: str, *, exclude_id: str | None = None
) -> bool:
    # `ilike` without wildcards is a case-insensitive equality check, matching
    # the DB's unique index on lower(name).
    query = (
        _client()
        .table("product_variants")
        .select("id")
        .eq("product_id", product_id)
        .ilike("name", name)
    )
    if exclude_id:
        query = query.neq("id", exclude_id)
    return bool((query.limit(1).execute()).data)
