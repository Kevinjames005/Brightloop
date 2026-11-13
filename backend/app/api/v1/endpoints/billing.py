"""API endpoints for Subscriptions, Billing, Invoices, Payments, Taxes, Discounts, and Reports."""

from __future__ import annotations

import secrets
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse

from app.core.config import get_settings
from app.core.dependencies import AdminUser, CurrentUser, require_roles
from app.schemas.subscription import (
    BillingRunRequest,
    BillingRunResult,
    DashboardMetrics,
    DiscountCreate,
    DiscountResponse,
    DiscountValidateRequest,
    DiscountValidateResponse,
    InvoiceCreate,
    InvoiceResponse,
    PaymentCreate,
    PaymentResponse,
    QuotationTemplateCreate,
    QuotationTemplateResponse,
    SubscriptionCreate,
    SubscriptionResponse,
    SubscriptionStatus,
    SubscriptionUpdate,
    TaxCreate,
    TaxResponse,
)
from app.schemas.user import UserRole
from app.services import billing_service, store

router = APIRouter()
StaffOrAdmin = Annotated[dict[str, Any], Depends(require_roles(UserRole.admin, UserRole.staff))]


def _owned_subscription(subscription_id: UUID, user: dict[str, Any]) -> dict[str, Any]:
    """Load a subscription and make sure the caller may act on it.

    Staff and admins may act on any subscription. A customer may only act on their own.
    """
    sub = store.get_subscription_by_id(subscription_id)
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subscription not found.")
    if user["role"] == UserRole.customer.value and sub.get("customer_id") != user["id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied.")
    return sub


# --------------------------------------------------------------------------- #
# Taxes
# --------------------------------------------------------------------------- #


@router.get("/taxes", response_model=list[TaxResponse], tags=["Taxes"])
def list_taxes(current_user: CurrentUser) -> list[TaxResponse]:
    taxes = store.get_taxes(active_only=False)
    return [TaxResponse.model_validate(t) for t in taxes]


@router.post("/taxes", response_model=TaxResponse, status_code=status.HTTP_201_CREATED, tags=["Taxes"])
def create_tax(payload: TaxCreate, current_user: AdminUser) -> TaxResponse:
    t = store.create_tax(payload.name, payload.rate, payload.is_active)
    return TaxResponse.model_validate(t)


# --------------------------------------------------------------------------- #
# Discounts
# --------------------------------------------------------------------------- #


@router.get("/discounts", response_model=list[DiscountResponse], tags=["Discounts"])
def list_discounts(current_user: StaffOrAdmin) -> list[DiscountResponse]:
    discounts = store.get_discounts()
    return [DiscountResponse.model_validate(d) for d in discounts]


@router.post("/discounts", response_model=DiscountResponse, status_code=status.HTTP_201_CREATED, tags=["Discounts"])
def create_discount(payload: DiscountCreate, current_user: AdminUser) -> DiscountResponse:
    existing = store.get_discount_by_code(payload.code)
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Discount code '{payload.code}' already exists.")
    d = store.create_discount(payload.model_dump())
    return DiscountResponse.model_validate(d)


@router.post("/discounts/validate", response_model=DiscountValidateResponse, tags=["Discounts"])
def validate_discount(payload: DiscountValidateRequest, current_user: CurrentUser) -> DiscountValidateResponse:
    disc = store.get_discount_by_code(payload.code)
    if not disc or not disc.get("is_active"):
        return DiscountValidateResponse(valid=False, reason="Discount code is invalid or inactive.")

    if disc.get("max_uses") and (disc.get("used_count", 0) >= disc["max_uses"]):
        return DiscountValidateResponse(valid=False, reason="Discount code usage limit reached.")

    if payload.subtotal < disc.get("min_purchase_amount", 0):
        return DiscountValidateResponse(
            valid=False,
            reason=f"Minimum purchase amount of ₹{disc['min_purchase_amount']} required.",
        )

    if payload.total_quantity < disc.get("min_quantity", 0):
        return DiscountValidateResponse(
            valid=False,
            reason=f"Minimum quantity of {disc['min_quantity']} items required.",
        )

    if disc.get("discount_type") == "percentage":
        amount = int(round(payload.subtotal * (disc.get("discount_value", 0) / 100.0)))
    else:
        amount = min(payload.subtotal, int(disc.get("discount_value", 0)))

    return DiscountValidateResponse(valid=True, discount_amount=amount, discount_id=disc.get("id"))


# --------------------------------------------------------------------------- #
# Quotation Templates
# --------------------------------------------------------------------------- #


@router.get("/quotation-templates", response_model=list[QuotationTemplateResponse], tags=["Quotations"])
def list_quotation_templates(current_user: CurrentUser) -> list[QuotationTemplateResponse]:
    templates = store.get_quotation_templates()
    return [QuotationTemplateResponse.model_validate(t) for t in templates]


@router.post("/quotation-templates", response_model=QuotationTemplateResponse, status_code=status.HTTP_201_CREATED, tags=["Quotations"])
def create_quotation_template(payload: QuotationTemplateCreate, current_user: StaffOrAdmin) -> QuotationTemplateResponse:
    t = store.create_quotation_template(payload.model_dump())
    return QuotationTemplateResponse.model_validate(t)


@router.post("/quotation-templates/{template_id}/create-quote", response_model=SubscriptionResponse, tags=["Quotations"])
def create_quote_from_template(
    template_id: UUID,
    current_user: CurrentUser,
    customer_id: UUID | None = None,
) -> SubscriptionResponse:
    # If customer calls, they can only create quote for themselves
    target_customer = str(customer_id) if customer_id and current_user["role"] != UserRole.customer.value else current_user["id"]
    try:
        sub = billing_service.create_subscription_from_template(str(template_id), target_customer)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    return SubscriptionResponse.model_validate(sub)


# --------------------------------------------------------------------------- #
# Subscriptions
# --------------------------------------------------------------------------- #


@router.get("/subscriptions", response_model=list[SubscriptionResponse], tags=["Subscriptions"])
def list_subscriptions(
    current_user: CurrentUser,
    status_filter: SubscriptionStatus | None = Query(default=None, alias="status"),
    customer_id: UUID | None = None,
) -> list[SubscriptionResponse]:
    # Customers only see their own subscriptions
    effective_customer_id = current_user["id"] if current_user["role"] == UserRole.customer.value else (str(customer_id) if customer_id else None)
    subs = store.get_subscriptions(
        customer_id=effective_customer_id,
        status=status_filter.value if status_filter else None,
    )
    return [SubscriptionResponse.model_validate(s) for s in subs]


@router.get("/subscriptions/{subscription_id}", response_model=SubscriptionResponse, tags=["Subscriptions"])
def get_subscription(subscription_id: UUID, current_user: CurrentUser) -> SubscriptionResponse:
    sub = store.get_subscription_by_id(subscription_id)
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subscription not found.")

    if current_user["role"] == UserRole.customer.value and sub.get("customer_id") != current_user["id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied.")

    return SubscriptionResponse.model_validate(sub)


@router.post("/subscriptions", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED, tags=["Subscriptions"])
def create_subscription(payload: SubscriptionCreate, current_user: CurrentUser) -> SubscriptionResponse:
    if current_user["role"] == UserRole.customer.value:
        if str(payload.customer_id) != current_user["id"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Customers can only create subscriptions for themselves.")
        # A customer's subscription is a request: it starts as a draft, is priced from the plan,
        # and carries no discount. Staff review it, adjust it if needed, and activate it.
        payload = payload.model_copy(
            update={"status": SubscriptionStatus.draft, "lines": [], "discount_id": None}
        )

    sub = billing_service.create_subscription(payload)
    return SubscriptionResponse.model_validate(sub)


@router.patch("/subscriptions/{subscription_id}", response_model=SubscriptionResponse, tags=["Subscriptions"])
def update_subscription(
    subscription_id: UUID,
    payload: SubscriptionUpdate,
    current_user: StaffOrAdmin,
) -> SubscriptionResponse:
    updates = payload.model_dump(exclude_unset=True)
    updated = store.update_subscription(str(subscription_id), updates)
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subscription not found.")
    return SubscriptionResponse.model_validate(updated)


@router.post("/subscriptions/{subscription_id}/to-quotation", response_model=SubscriptionResponse, tags=["Subscriptions"])
def convert_to_quotation(subscription_id: UUID, current_user: CurrentUser) -> SubscriptionResponse:
    _owned_subscription(subscription_id, current_user)
    try:
        sub = billing_service.transition_subscription(str(subscription_id), SubscriptionStatus.quotation)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return SubscriptionResponse.model_validate(sub)


@router.post("/subscriptions/{subscription_id}/confirm", response_model=SubscriptionResponse, tags=["Subscriptions"])
def confirm_subscription(subscription_id: UUID, current_user: CurrentUser) -> SubscriptionResponse:
    _owned_subscription(subscription_id, current_user)
    try:
        sub = billing_service.transition_subscription(str(subscription_id), SubscriptionStatus.confirmed)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return SubscriptionResponse.model_validate(sub)


@router.post("/subscriptions/{subscription_id}/activate", response_model=SubscriptionResponse, tags=["Subscriptions"])
def activate_subscription(subscription_id: UUID, current_user: StaffOrAdmin) -> SubscriptionResponse:
    try:
        sub = billing_service.transition_subscription(str(subscription_id), SubscriptionStatus.active)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return SubscriptionResponse.model_validate(sub)


@router.post("/subscriptions/{subscription_id}/pause", response_model=SubscriptionResponse, tags=["Subscriptions"])
def pause_subscription(subscription_id: UUID, current_user: CurrentUser) -> SubscriptionResponse:
    _owned_subscription(subscription_id, current_user)
    try:
        sub = billing_service.transition_subscription(str(subscription_id), SubscriptionStatus.paused)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return SubscriptionResponse.model_validate(sub)


@router.post("/subscriptions/{subscription_id}/resume", response_model=SubscriptionResponse, tags=["Subscriptions"])
def resume_subscription(subscription_id: UUID, current_user: CurrentUser) -> SubscriptionResponse:
    _owned_subscription(subscription_id, current_user)
    try:
        sub = billing_service.transition_subscription(str(subscription_id), SubscriptionStatus.active)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return SubscriptionResponse.model_validate(sub)


@router.post("/subscriptions/{subscription_id}/close", response_model=SubscriptionResponse, tags=["Subscriptions"])
def close_subscription(subscription_id: UUID, current_user: CurrentUser) -> SubscriptionResponse:
    _owned_subscription(subscription_id, current_user)
    try:
        sub = billing_service.transition_subscription(str(subscription_id), SubscriptionStatus.closed)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return SubscriptionResponse.model_validate(sub)


@router.post("/subscriptions/{subscription_id}/renew", response_model=SubscriptionResponse, tags=["Subscriptions"])
def renew_subscription(
    subscription_id: UUID,
    current_user: CurrentUser,
    additional_months: int = Query(default=12, ge=1, le=60),
) -> SubscriptionResponse:
    existing = _owned_subscription(subscription_id, current_user)
    # Renewing re-activates a subscription, so a customer may only renew one that has already
    # been activated at some point. Staff can renew any subscription.
    if current_user["role"] == UserRole.customer.value and existing.get("status") not in ("active", "paused", "closed"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only active, paused or closed subscriptions can be renewed.")
    try:
        sub = billing_service.renew_subscription(str(subscription_id), additional_months=additional_months)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return SubscriptionResponse.model_validate(sub)


# --------------------------------------------------------------------------- #
# Automated Billing Day Run
# --------------------------------------------------------------------------- #


@router.post("/billing/run", response_model=BillingRunResult, tags=["Billing"])
def run_billing(payload: BillingRunRequest, current_user: StaffOrAdmin) -> BillingRunResult:
    """Executes automated recurring billing run ("Billing Day")."""
    return billing_service.run_billing_day(payload)


@router.get("/billing/preview", response_model=BillingRunResult, tags=["Billing"])
def preview_billing(current_user: StaffOrAdmin) -> BillingRunResult:
    """Dry-run preview of subscriptions currently due for recurring invoice generation."""
    return billing_service.run_billing_day(BillingRunRequest(dry_run=True))


# --------------------------------------------------------------------------- #
# Invoices
# --------------------------------------------------------------------------- #


@router.get("/invoices", response_model=list[InvoiceResponse], tags=["Invoices"])
def list_invoices(
    current_user: CurrentUser,
    status_filter: str | None = Query(default=None, alias="status"),
    overdue_only: bool = False,
    customer_id: UUID | None = None,
) -> list[InvoiceResponse]:
    effective_customer_id = current_user["id"] if current_user["role"] == UserRole.customer.value else (str(customer_id) if customer_id else None)
    invoices = store.get_invoices(
        customer_id=effective_customer_id,
        status=status_filter,
        overdue_only=overdue_only,
    )
    return [InvoiceResponse.model_validate(inv) for inv in invoices]


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse, tags=["Invoices"])
def get_invoice(invoice_id: UUID, current_user: CurrentUser) -> InvoiceResponse:
    inv = store.get_invoice_by_id(invoice_id)
    if not inv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found.")

    if current_user["role"] == UserRole.customer.value and inv.get("customer_id") != current_user["id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied.")

    return InvoiceResponse.model_validate(inv)


@router.post("/invoices/{invoice_id}/confirm", response_model=InvoiceResponse, tags=["Invoices"])
def confirm_invoice(invoice_id: UUID, current_user: StaffOrAdmin) -> InvoiceResponse:
    updated = store.update_invoice(str(invoice_id), {"status": "confirmed"})
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found.")
    return InvoiceResponse.model_validate(updated)


@router.post("/invoices/{invoice_id}/cancel", response_model=InvoiceResponse, tags=["Invoices"])
def cancel_invoice(invoice_id: UUID, current_user: StaffOrAdmin) -> InvoiceResponse:
    updated = store.update_invoice(str(invoice_id), {"status": "cancelled"})
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found.")
    return InvoiceResponse.model_validate(updated)


@router.post("/invoices/{invoice_id}/send", response_model=InvoiceResponse, tags=["Invoices"])
def send_invoice(invoice_id: UUID, current_user: StaffOrAdmin) -> InvoiceResponse:
    now_str = datetime.utcnow().isoformat()
    updated = store.update_invoice(str(invoice_id), {"sent_at": now_str})
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found.")
    return InvoiceResponse.model_validate(updated)


@router.get("/invoices/{invoice_id}/print", response_class=HTMLResponse, tags=["Invoices"])
def print_invoice(invoice_id: UUID, current_user: CurrentUser) -> HTMLResponse:
    inv = store.get_invoice_by_id(invoice_id)
    if not inv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found.")
    if current_user["role"] == UserRole.customer.value and inv.get("customer_id") != current_user["id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied.")

    html = billing_service.generate_printable_invoice_html(str(invoice_id))
    return HTMLResponse(content=html)


# --------------------------------------------------------------------------- #
# Payments
# --------------------------------------------------------------------------- #


@router.get("/payments", response_model=list[PaymentResponse], tags=["Payments"])
def list_payments(
    current_user: CurrentUser,
    invoice_id: UUID | None = None,
    customer_id: UUID | None = None,
) -> list[PaymentResponse]:
    effective_customer_id = current_user["id"] if current_user["role"] == UserRole.customer.value else (str(customer_id) if customer_id else None)
    payments = store.get_payments(
        invoice_id=str(invoice_id) if invoice_id else None,
        customer_id=effective_customer_id,
    )
    return [PaymentResponse.model_validate(p) for p in payments]


@router.post("/payments", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED, tags=["Payments"])
def record_payment(payload: PaymentCreate, current_user: CurrentUser) -> PaymentResponse:
    inv = store.get_invoice_by_id(payload.invoice_id)
    if not inv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found.")

    if current_user["role"] == UserRole.customer.value and inv.get("customer_id") != current_user["id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Access denied.")

    try:
        p = billing_service.record_payment(payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return PaymentResponse.model_validate(p)


# --------------------------------------------------------------------------- #
# Finance Reports & Executive Dashboard
# --------------------------------------------------------------------------- #


@router.get("/reports/dashboard", response_model=DashboardMetrics, tags=["Reports"])
def get_finance_dashboard(current_user: StaffOrAdmin) -> DashboardMetrics:
    """Consolidated financial intelligence dashboard for the finance lead."""
    return billing_service.get_dashboard_metrics()


# --------------------------------------------------------------------------- #
# Demo Seeder
# --------------------------------------------------------------------------- #


@router.post("/demo/seed", tags=["Demo"])
def seed_demo_environment(
    x_bootstrap_token: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """Load sample products, plans, subscriptions, invoices and payments.

    This REPLACES the catalog and billing rows, so it is locked behind the same
    `BOOTSTRAP_TOKEN` used to create the first admin. With no token configured it is disabled.
    """
    expected = get_settings().bootstrap_token
    if not expected:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Demo data is disabled. Set BOOTSTRAP_TOKEN in backend/.env to enable it.",
        )
    # Compare as bytes: compare_digest rejects non-ASCII str inputs.
    if not x_bootstrap_token or not secrets.compare_digest(
        x_bootstrap_token.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid or missing X-Bootstrap-Token.")
    return billing_service.seed_demo_data()
