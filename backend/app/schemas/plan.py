"""Pydantic schemas for plans (pricing)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.money import Rupees
from app.schemas.common import DisplayName, StrictBool


class BillingInterval(str, Enum):
    day = "day"
    week = "week"
    month = "month"
    year = "year"


IntervalCount = Annotated[int, Field(strict=True, ge=1, le=36)]
TrialDays = Annotated[int, Field(strict=True, ge=0, le=365)]


class PlanCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "variant_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "name": "Standard - Quarterly",
                "billing_interval": "month",
                "interval_count": 3,
                "price_inr": 2699,
                "trial_days": 14,
            }
        }
    )

    variant_id: UUID
    name: DisplayName
    billing_interval: BillingInterval = BillingInterval.month
    interval_count: IntervalCount = 1
    # 2699 = ₹2,699. Floats/strings are rejected (strict int).
    price_inr: Rupees
    trial_days: TrialDays = 0


class PlanUpdate(BaseModel):
    """`variant_id` and `currency` are immutable."""

    name: DisplayName | None = None
    billing_interval: BillingInterval | None = None
    interval_count: IntervalCount | None = None
    price_inr: Rupees | None = None
    trial_days: TrialDays | None = None
    is_active: StrictBool | None = None

    @model_validator(mode="after")
    def _check_patch(self) -> "PlanUpdate":
        provided = self.model_fields_set
        if not provided:
            raise ValueError("Provide at least one field to update.")
        for field in ("name", "billing_interval", "interval_count", "price_inr",
                      "trial_days", "is_active"):
            if field in provided and getattr(self, field) is None:
                raise ValueError(f"'{field}' cannot be null.")
        return self


class PlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    variant_id: UUID
    name: str
    billing_interval: BillingInterval
    interval_count: int
    price_inr: int = Field(description="Price in whole rupees.")
    currency: str
    trial_days: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PaginatedPlans(BaseModel):
    items: list[PlanResponse]
    total: int = Field(description="Total matching plans, before pagination.")
    limit: int
    offset: int
