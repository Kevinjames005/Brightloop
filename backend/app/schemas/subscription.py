"""Pydantic schemas for subscriptions, quotations, taxes, discounts, invoices, and payments."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.money import Rupees
from app.schemas.common import DisplayName, StrictBool


class SubscriptionStatus(str, Enum):
    draft = "draft"
    quotation = "quotation"
    confirmed = "confirmed"
    active = "active"
    paused = "paused"
    closed = "closed"


class PaymentTerms(str, Enum):
    immediate = "immediate"
    net15 = "net15"
    net30 = "net30"
    net60 = "net60"


class DiscountType(str, Enum):
    percentage = "percentage"
    fixed = "fixed"


class DiscountAppliesTo(str, Enum):
    whole_subscription = "whole_subscription"
    product = "product"


class InvoiceStatus(str, Enum):
    draft = "draft"
    confirmed = "confirmed"
    paid = "paid"
    cancelled = "cancelled"


class PaymentMethod(str, Enum):
    bank_transfer = "bank_transfer"
    credit_card = "credit_card"
    upi = "upi"
    cash = "cash"
    cheque = "cheque"
    portal_online = "portal_online"


# --------------------------------------------------------------------------- #
# Taxes
# --------------------------------------------------------------------------- #


class TaxCreate(BaseModel):
    name: str = Field(min_length=2, max_length=50, example="GST 18%")
    rate: float = Field(ge=0, le=100, example=18.0)
    is_active: bool = True


class TaxResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    rate: float
    is_active: bool
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Discounts
# --------------------------------------------------------------------------- #


class DiscountCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32, example="STARTUP20")
    description: str | None = None
    discount_type: DiscountType = DiscountType.percentage
    discount_value: float = Field(gt=0, example=20.0)
    min_purchase_amount: int = Field(ge=0, default=0, description="Minimum purchase in INR")
    min_quantity: int = Field(ge=0, default=0)
    start_date: datetime | None = None
    end_date: datetime | None = None
    max_uses: int | None = Field(default=None, ge=1)
    applies_to: DiscountAppliesTo = DiscountAppliesTo.whole_subscription
    product_id: UUID | None = None
    is_active: bool = True


class DiscountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    description: str | None
    discount_type: DiscountType
    discount_value: float
    min_purchase_amount: int
    min_quantity: int
    start_date: datetime | None
    end_date: datetime | None
    max_uses: int | None
    used_count: int
    applies_to: DiscountAppliesTo
    product_id: UUID | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DiscountValidateRequest(BaseModel):
    code: str
    subtotal: int
    total_quantity: int
    product_ids: list[UUID] = []


class DiscountValidateResponse(BaseModel):
    valid: bool
    reason: str | None = None
    discount_amount: int = 0
    discount_id: UUID | None = None


# --------------------------------------------------------------------------- #
# Quotation Templates
# --------------------------------------------------------------------------- #


class QuotationTemplateLine(BaseModel):
    product_id: UUID
    variant_id: UUID | None = None
    quantity: int = Field(ge=1, default=1)
    unit_price: int = Field(ge=0, default=0)
    tax_id: UUID | None = None


class QuotationTemplateCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120, example="Enterprise CRM Suite")
    description: str | None = None
    plan_id: UUID | None = None
    valid_days: int = Field(ge=1, le=365, default=30)
    lines: list[QuotationTemplateLine] = []
    is_active: bool = True


class QuotationTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    plan_id: UUID | None
    valid_days: int
    lines: list[dict[str, Any]]
    is_active: bool
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Subscriptions
# --------------------------------------------------------------------------- #


class SubscriptionLineCreate(BaseModel):
    product_id: UUID
    variant_id: UUID | None = None
    quantity: int = Field(ge=1, default=1)
    unit_price: int = Field(ge=0, description="Unit price in whole INR")
    tax_id: UUID | None = None


class SubscriptionLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subscription_id: UUID
    product_id: UUID
    variant_id: UUID | None
    quantity: int
    unit_price: int
    tax_id: UUID | None
    tax_rate: float
    amount: int
    product_name: str | None = None
    variant_name: str | None = None


class SubscriptionCreate(BaseModel):
    customer_id: UUID
    plan_id: UUID
    start_date: date = Field(default_factory=date.today)
    expiry_date: date | None = None
    payment_terms: PaymentTerms = PaymentTerms.immediate
    lines: list[SubscriptionLineCreate] = []
    discount_id: UUID | None = None
    notes: str | None = None
    auto_close: bool = False
    status: SubscriptionStatus = SubscriptionStatus.draft


class SubscriptionUpdate(BaseModel):
    plan_id: UUID | None = None
    expiry_date: date | None = None
    payment_terms: PaymentTerms | None = None
    notes: str | None = None
    auto_close: bool | None = None
    discount_id: UUID | None = None


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subscription_number: str
    customer_id: UUID
    customer_name: str | None = None
    customer_email: str | None = None
    plan_id: UUID
    plan_name: str | None = None
    status: SubscriptionStatus
    start_date: date
    expiry_date: date | None
    payment_terms: PaymentTerms
    next_billing_date: date | None
    last_billed_date: date | None
    auto_close: bool
    discount_id: UUID | None
    notes: str | None
    lines: list[SubscriptionLineResponse] = []
    total_recurring_amount: int = 0
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Invoices
# --------------------------------------------------------------------------- #


class InvoiceLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    invoice_id: UUID
    product_id: UUID | None
    description: str
    quantity: int
    unit_price: int
    tax_rate: float
    tax_amount: int
    discount_amount: int
    total_amount: int


class InvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    invoice_number: str
    subscription_id: UUID | None
    subscription_number: str | None = None
    customer_id: UUID
    customer_name: str | None = None
    customer_email: str | None = None
    status: InvoiceStatus
    subtotal: int
    tax_total: int
    discount_total: int
    total_amount: int
    amount_paid: int
    balance_due: int = 0
    billing_period_start: date | None
    billing_period_end: date | None
    issue_date: date
    due_date: date
    sent_at: datetime | None
    notes: str | None
    lines: list[InvoiceLineResponse] = []
    is_overdue: bool = False
    created_at: datetime
    updated_at: datetime


class InvoiceCreate(BaseModel):
    subscription_id: UUID | None = None
    customer_id: UUID
    issue_date: date = Field(default_factory=date.today)
    due_date: date | None = None
    notes: str | None = None
    lines: list[dict[str, Any]] = []


# --------------------------------------------------------------------------- #
# Payments
# --------------------------------------------------------------------------- #


class PaymentCreate(BaseModel):
    invoice_id: UUID
    amount: int = Field(gt=0, description="Payment amount in whole INR")
    payment_method: PaymentMethod = PaymentMethod.bank_transfer
    payment_date: date = Field(default_factory=date.today)
    note: str | None = None


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    payment_number: str
    invoice_id: UUID
    invoice_number: str | None = None
    customer_name: str | None = None
    amount: int
    payment_method: PaymentMethod
    payment_date: date
    note: str | None
    created_at: datetime


# --------------------------------------------------------------------------- #
# Billing Run & Dashboard
# --------------------------------------------------------------------------- #


class BillingRunRequest(BaseModel):
    billing_date: date = Field(default_factory=date.today)
    customer_id: UUID | None = None
    dry_run: bool = False


class BillingRunResult(BaseModel):
    processed_count: int
    invoices_created: int
    skipped_count: int
    total_billed: int
    invoices: list[InvoiceResponse] = []


class DashboardMetrics(BaseModel):
    active_subscriptions: int
    total_revenue_collected: int
    total_outstanding: int
    overdue_invoices_count: int
    overdue_amount: int
    monthly_recurring_revenue: int
    annual_run_rate: int
    total_customers: int
    total_invoices: int
    recent_invoices: list[InvoiceResponse] = []
    recent_payments: list[PaymentResponse] = []
    overdue_invoices: list[InvoiceResponse] = []
