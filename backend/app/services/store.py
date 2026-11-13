"""Data store for taxes, discounts, quotations, subscriptions, invoices and payments.

Supabase (Postgres) is the single source of truth. The tables are created by
`sql/005_subscriptions_billing.sql`; run it in the Supabase SQL editor first.

Every read returns plain dicts shaped for the Pydantic response models in
`app/schemas/subscription.py` (names of customers/plans/products are joined in,
`lines` and `total_recurring_amount` are filled, and so on).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable
from uuid import UUID, uuid4

from postgrest.exceptions import APIError

from app.core.database import get_supabase
from app.core.db_errors import is_unique_violation

logger = logging.getLogger(__name__)

_CHUNK = 100  # ids per `in (...)` filter, keeps the request URL short


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    """Recursively convert UUID/date/Decimal values into JSON-friendly ones."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _fetch_in(table: str, column: str, ids: Iterable[Any], select: str = "*") -> list[dict[str, Any]]:
    """`select ... where column in ids`, chunked. Ignores empty/None ids."""
    unique = sorted({str(i) for i in ids if i})
    rows: list[dict[str, Any]] = []
    for start in range(0, len(unique), _CHUNK):
        chunk = unique[start : start + _CHUNK]
        rows.extend(get_supabase().table(table).select(select).in_(column, chunk).execute().data or [])
    return rows


def _next_number(table: str, column: str, prefix: str) -> str:
    """Next human-readable number like SUB-2026-0007 (max existing + 1)."""
    stem = f"{prefix}-{datetime.now().year}-"
    rows = (
        get_supabase().table(table).select(column).like(column, f"{stem}%").execute().data or []
    )
    highest = 0
    for row in rows:
        tail = str(row[column])[len(stem) :]
        if tail.isdigit():
            highest = max(highest, int(tail))
    return f"{stem}{highest + 1:04d}"


def _insert_numbered(table: str, record: dict[str, Any], column: str, prefix: str) -> dict[str, Any]:
    """Insert `record` with a fresh number, retrying if a concurrent insert took it."""
    last_error: APIError | None = None
    for _ in range(5):
        record[column] = _next_number(table, column, prefix)
        try:
            res = get_supabase().table(table).insert(_json_safe(record)).execute()
            return (res.data or [record])[0]
        except APIError as exc:
            if not is_unique_violation(exc):
                raise
            last_error = exc
    assert last_error is not None
    raise last_error


# --------------------------------------------------------------------------- #
# Plans / users (read-only helpers used by billing)
# --------------------------------------------------------------------------- #


def get_plan_by_id(plan_id: UUID | str) -> dict[str, Any] | None:
    res = get_supabase().table("plans").select("*").eq("id", str(plan_id)).limit(1).execute()
    return res.data[0] if res.data else None


def count_customers() -> int:
    res = get_supabase().table("users").select("id", count="exact").eq("role", "customer").limit(1).execute()
    return int(res.count or 0)


# --------------------------------------------------------------------------- #
# Taxes
# --------------------------------------------------------------------------- #


def get_taxes(active_only: bool = True) -> list[dict[str, Any]]:
    q = get_supabase().table("taxes").select("*")
    if active_only:
        q = q.eq("is_active", True)
    return q.order("rate").execute().data or []


def get_tax_by_id(tax_id: UUID | str) -> dict[str, Any] | None:
    res = get_supabase().table("taxes").select("*").eq("id", str(tax_id)).limit(1).execute()
    return res.data[0] if res.data else None


def create_tax(name: str, rate: float, is_active: bool = True) -> dict[str, Any]:
    record = {"name": name, "rate": rate, "is_active": is_active}
    return get_supabase().table("taxes").insert(record).execute().data[0]


# --------------------------------------------------------------------------- #
# Discounts
# --------------------------------------------------------------------------- #


def get_discounts(active_only: bool = False) -> list[dict[str, Any]]:
    q = get_supabase().table("discounts").select("*")
    if active_only:
        q = q.eq("is_active", True)
    return q.order("created_at", desc=True).execute().data or []


def get_discount_by_id(discount_id: UUID | str) -> dict[str, Any] | None:
    res = get_supabase().table("discounts").select("*").eq("id", str(discount_id)).limit(1).execute()
    return res.data[0] if res.data else None


def get_discount_by_code(code: str) -> dict[str, Any] | None:
    res = (
        get_supabase().table("discounts").select("*").eq("code", code.strip().upper()).limit(1).execute()
    )
    return res.data[0] if res.data else None


def create_discount(data: dict[str, Any]) -> dict[str, Any]:
    record = {
        "code": data["code"].strip().upper(),
        "description": data.get("description"),
        "discount_type": data.get("discount_type", "percentage"),
        "discount_value": float(data.get("discount_value", 0)),
        "min_purchase_amount": int(data.get("min_purchase_amount", 0)),
        "min_quantity": int(data.get("min_quantity", 0)),
        "start_date": data.get("start_date"),
        "end_date": data.get("end_date"),
        "max_uses": data.get("max_uses"),
        "used_count": 0,
        "applies_to": data.get("applies_to", "whole_subscription"),
        "product_id": data.get("product_id"),
        "is_active": bool(data.get("is_active", True)),
    }
    return get_supabase().table("discounts").insert(_json_safe(record)).execute().data[0]


def increment_discount_used_count(discount_id: str) -> None:
    current = get_discount_by_id(discount_id)
    if current:
        (
            get_supabase()
            .table("discounts")
            .update({"used_count": (current.get("used_count") or 0) + 1, "updated_at": _now()})
            .eq("id", str(discount_id))
            .execute()
        )


# --------------------------------------------------------------------------- #
# Quotation templates
# --------------------------------------------------------------------------- #


def get_quotation_templates() -> list[dict[str, Any]]:
    return get_supabase().table("quotation_templates").select("*").order("created_at", desc=True).execute().data or []


def get_quotation_template_by_id(template_id: UUID | str) -> dict[str, Any] | None:
    res = (
        get_supabase().table("quotation_templates").select("*").eq("id", str(template_id)).limit(1).execute()
    )
    return res.data[0] if res.data else None


def create_quotation_template(data: dict[str, Any]) -> dict[str, Any]:
    record = {
        "name": data["name"],
        "description": data.get("description"),
        "plan_id": data.get("plan_id"),
        "valid_days": int(data.get("valid_days", 30)),
        "lines": data.get("lines", []),
        "is_active": bool(data.get("is_active", True)),
    }
    return get_supabase().table("quotation_templates").insert(_json_safe(record)).execute().data[0]


# --------------------------------------------------------------------------- #
# Subscriptions
# --------------------------------------------------------------------------- #

_SUB_SELECT = "*, subscription_lines(*)"


def _hydrate_subscriptions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add customer/plan/product names, `lines` and `total_recurring_amount`."""
    if not rows:
        return rows
    users = {u["id"]: u for u in _fetch_in("users", "id", (r["customer_id"] for r in rows), "id,name,email")}
    plans = {p["id"]: p for p in _fetch_in("plans", "id", (r["plan_id"] for r in rows), "id,name")}
    all_lines = [ln for r in rows for ln in (r.get("subscription_lines") or [])]
    products = {p["id"]: p for p in _fetch_in("products", "id", (ln["product_id"] for ln in all_lines), "id,name")}
    variants = {v["id"]: v for v in _fetch_in("product_variants", "id", (ln.get("variant_id") for ln in all_lines), "id,name")}

    for r in rows:
        lines = r.get("subscription_lines") or []
        for ln in lines:
            ln["product_name"] = (products.get(ln["product_id"]) or {}).get("name")
            ln["variant_name"] = (variants.get(ln.get("variant_id")) or {}).get("name")
        cust = users.get(r["customer_id"]) or {}
        r["customer_name"] = cust.get("name")
        r["customer_email"] = cust.get("email")
        r["plan_name"] = (plans.get(r["plan_id"]) or {}).get("name")
        r["subscription_lines"] = lines  # used by billing_service
        r["lines"] = lines  # used by SubscriptionResponse
        r["total_recurring_amount"] = sum(int(ln.get("amount") or 0) for ln in lines)
    return rows


def get_subscriptions(customer_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    q = get_supabase().table("subscriptions").select(_SUB_SELECT)
    if customer_id:
        q = q.eq("customer_id", str(customer_id))
    if status:
        q = q.eq("status", status)
    rows = q.order("created_at", desc=True).execute().data or []
    return _hydrate_subscriptions(rows)


def get_subscription_by_id(subscription_id: UUID | str) -> dict[str, Any] | None:
    res = (
        get_supabase().table("subscriptions").select(_SUB_SELECT).eq("id", str(subscription_id)).limit(1).execute()
    )
    rows = _hydrate_subscriptions(res.data or [])
    return rows[0] if rows else None


def create_subscription(sub_data: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, Any]:
    start = sub_data.get("start_date", date.today())
    record = {
        "customer_id": str(sub_data["customer_id"]),
        "plan_id": str(sub_data["plan_id"]),
        "status": sub_data.get("status", "draft"),
        "start_date": start,
        "expiry_date": sub_data.get("expiry_date"),
        "payment_terms": sub_data.get("payment_terms", "immediate"),
        "next_billing_date": sub_data.get("next_billing_date", start),
        "last_billed_date": None,
        "auto_close": bool(sub_data.get("auto_close", False)),
        "discount_id": sub_data.get("discount_id"),
        "notes": sub_data.get("notes"),
    }
    created = _insert_numbered("subscriptions", record, "subscription_number", "SUB")
    sub_id = created["id"]

    if lines:
        line_rows = []
        for line in lines:
            qty = int(line.get("quantity", 1))
            unit = int(line.get("unit_price", 0))
            line_rows.append(
                {
                    "subscription_id": sub_id,
                    "product_id": str(line["product_id"]),
                    "variant_id": line.get("variant_id"),
                    "quantity": qty,
                    "unit_price": unit,
                    "tax_id": line.get("tax_id"),
                    "tax_rate": float(line.get("tax_rate", 0)),
                    "amount": int(line.get("amount", qty * unit)),
                }
            )
        try:
            get_supabase().table("subscription_lines").insert(_json_safe(line_rows)).execute()
        except Exception:
            # Don't leave a subscription without the lines the caller asked for.
            get_supabase().table("subscriptions").delete().eq("id", sub_id).execute()
            raise
    return get_subscription_by_id(sub_id) or created


def update_subscription(sub_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    payload = _json_safe({**updates, "updated_at": _now()})
    res = get_supabase().table("subscriptions").update(payload).eq("id", str(sub_id)).execute()
    if not res.data:
        return None
    return get_subscription_by_id(sub_id)


# --------------------------------------------------------------------------- #
# Invoices
# --------------------------------------------------------------------------- #

_INV_SELECT = "*, invoice_lines(*)"


def _hydrate_invoices(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    users = {u["id"]: u for u in _fetch_in("users", "id", (r["customer_id"] for r in rows), "id,name,email")}
    subs = {s["id"]: s for s in _fetch_in("subscriptions", "id", (r.get("subscription_id") for r in rows), "id,subscription_number")}
    today = date.today().isoformat()
    for r in rows:
        r["lines"] = r.get("invoice_lines") or []
        cust = users.get(r["customer_id"]) or {}
        r["customer_name"] = cust.get("name")
        r["customer_email"] = cust.get("email")
        r["subscription_number"] = (subs.get(r.get("subscription_id")) or {}).get("subscription_number")
        r["balance_due"] = max(0, int(r["total_amount"]) - int(r["amount_paid"]))
        r["is_overdue"] = str(r["due_date"]) < today and r["status"] not in ("paid", "cancelled")
    return rows


def get_invoices(
    customer_id: str | None = None, status: str | None = None, overdue_only: bool = False
) -> list[dict[str, Any]]:
    q = get_supabase().table("invoices").select(_INV_SELECT)
    if customer_id:
        q = q.eq("customer_id", str(customer_id))
    if status:
        q = q.eq("status", status)
    rows = _hydrate_invoices(q.order("created_at", desc=True).execute().data or [])
    return [r for r in rows if r["is_overdue"]] if overdue_only else rows


def get_invoice_by_id(invoice_id: UUID | str) -> dict[str, Any] | None:
    res = get_supabase().table("invoices").select(_INV_SELECT).eq("id", str(invoice_id)).limit(1).execute()
    rows = _hydrate_invoices(res.data or [])
    return rows[0] if rows else None


def create_invoice(inv_data: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, Any]:
    record = {
        "subscription_id": inv_data.get("subscription_id"),
        "customer_id": str(inv_data["customer_id"]),
        "status": inv_data.get("status", "draft"),
        "subtotal": int(inv_data.get("subtotal", 0)),
        "tax_total": int(inv_data.get("tax_total", 0)),
        "discount_total": int(inv_data.get("discount_total", 0)),
        "total_amount": int(inv_data.get("total_amount", 0)),
        "amount_paid": int(inv_data.get("amount_paid", 0)),
        "billing_period_start": inv_data.get("billing_period_start"),
        "billing_period_end": inv_data.get("billing_period_end"),
        "issue_date": inv_data.get("issue_date", date.today()),
        "due_date": inv_data.get("due_date", date.today()),
        "sent_at": inv_data.get("sent_at"),
        "notes": inv_data.get("notes"),
    }
    created = _insert_numbered("invoices", record, "invoice_number", "INV")
    inv_id = created["id"]

    if lines:
        line_rows = [
            {
                "invoice_id": inv_id,
                "product_id": line.get("product_id"),
                "description": line["description"],
                "quantity": int(line.get("quantity", 1)),
                "unit_price": int(line.get("unit_price", 0)),
                "tax_rate": float(line.get("tax_rate", 0)),
                "tax_amount": int(line.get("tax_amount", 0)),
                "discount_amount": int(line.get("discount_amount", 0)),
                "total_amount": int(line.get("total_amount", 0)),
            }
            for line in lines
        ]
        try:
            get_supabase().table("invoice_lines").insert(_json_safe(line_rows)).execute()
        except Exception:
            get_supabase().table("invoices").delete().eq("id", inv_id).execute()
            raise
    return get_invoice_by_id(inv_id) or created


def update_invoice(invoice_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    payload = _json_safe({**updates, "updated_at": _now()})
    res = get_supabase().table("invoices").update(payload).eq("id", str(invoice_id)).execute()
    if not res.data:
        return None
    return get_invoice_by_id(invoice_id)


# --------------------------------------------------------------------------- #
# Payments
# --------------------------------------------------------------------------- #


def _hydrate_payments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    invoices = {i["id"]: i for i in _fetch_in("invoices", "id", (r["invoice_id"] for r in rows), "id,invoice_number,customer_id")}
    users = {u["id"]: u for u in _fetch_in("users", "id", (i["customer_id"] for i in invoices.values()), "id,name")}
    for r in rows:
        inv = invoices.get(r["invoice_id"]) or {}
        r["invoice_number"] = inv.get("invoice_number")
        r["customer_name"] = (users.get(inv.get("customer_id")) or {}).get("name")
    return rows


def get_payments(invoice_id: str | None = None, customer_id: str | None = None) -> list[dict[str, Any]]:
    q = get_supabase().table("payments").select("*")
    if invoice_id:
        q = q.eq("invoice_id", str(invoice_id))
    if customer_id:
        ids = [
            r["id"]
            for r in get_supabase().table("invoices").select("id").eq("customer_id", str(customer_id)).execute().data or []
        ]
        if not ids:
            return []
        q = q.in_("invoice_id", ids)
    return _hydrate_payments(q.order("created_at", desc=True).execute().data or [])


def create_payment(payment_data: dict[str, Any]) -> dict[str, Any]:
    """Record a payment and roll it into the invoice's `amount_paid` / status."""
    invoice_id = str(payment_data["invoice_id"])
    amount = int(payment_data["amount"])
    record = {
        "invoice_id": invoice_id,
        "amount": amount,
        "payment_method": payment_data.get("payment_method", "bank_transfer"),
        "payment_date": payment_data.get("payment_date", date.today()),
        "note": payment_data.get("note"),
    }
    created = _insert_numbered("payments", record, "payment_number", "PAY")

    sb = get_supabase()
    for _ in range(5):  # optimistic retry: another payment may land concurrently
        inv = sb.table("invoices").select("total_amount,amount_paid,status").eq("id", invoice_id).limit(1).execute().data
        if not inv:
            break
        inv = inv[0]
        new_paid = int(inv["amount_paid"] or 0) + amount
        status = "paid" if new_paid >= int(inv["total_amount"]) else inv["status"]
        if status == "draft":
            status = "confirmed"
        res = (
            sb.table("invoices")
            .update({"amount_paid": new_paid, "status": status, "updated_at": _now()})
            .eq("id", invoice_id)
            .eq("amount_paid", inv["amount_paid"])
            .execute()
        )
        if res.data:
            break

    rows = _hydrate_payments([created])
    return rows[0]


# --------------------------------------------------------------------------- #
# Password resets
# --------------------------------------------------------------------------- #


def create_password_reset(user_id: str, token: str, expires_at: datetime) -> None:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    get_supabase().table("password_resets").insert(
        {"user_id": str(user_id), "token": token, "expires_at": expires_at.isoformat(), "used": False}
    ).execute()


def get_password_reset(token: str) -> dict[str, Any] | None:
    res = (
        get_supabase().table("password_resets").select("*").eq("token", token).eq("used", False).limit(1).execute()
    )
    return res.data[0] if res.data else None


def mark_password_reset_used(token: str) -> None:
    get_supabase().table("password_resets").update({"used": True}).eq("token", token).execute()


# --------------------------------------------------------------------------- #
# Maintenance (used by the demo seeder)
# --------------------------------------------------------------------------- #

_ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def clear_business_data() -> None:
    """Delete catalog + billing rows (children first). Users are never touched."""
    sb = get_supabase()
    for table in (
        "payments",
        "invoice_lines",
        "invoices",
        "subscription_lines",
        "subscriptions",
        "quotation_templates",
        "discounts",
        "taxes",
        "plans",
        "product_variants",
        "products",
        "password_resets",
    ):
        sb.table(table).delete().neq("id", _ZERO_UUID).execute()
