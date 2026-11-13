"""Pydantic schemas for products and product variants."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import Description, DisplayName, Sku, StrictBool


def _validate_patch(model: BaseModel, non_nullable: tuple[str, ...]) -> None:
    """Require at least one field and reject explicit nulls for required columns."""
    provided = model.model_fields_set
    if not provided:
        raise ValueError("Provide at least one field to update.")
    for field in non_nullable:
        if field in provided and getattr(model, field) is None:
            raise ValueError(f"'{field}' cannot be null.")


class ProductCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "sku": "brightloop-crm",
                "name": "Brightloop CRM",
                "description": "Customer relationship management suite",
            }
        }
    )

    sku: Sku
    name: DisplayName
    description: Description = None


class ProductUpdate(BaseModel):
    sku: Sku | None = None
    name: DisplayName | None = None
    description: Description = None
    is_active: StrictBool | None = None

    @model_validator(mode="after")
    def _check_patch(self) -> "ProductUpdate":
        _validate_patch(self, ("sku", "name", "is_active"))
        return self


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku: str
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class VariantCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "product_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "sku": "brightloop-crm-standard",
                "name": "Standard",
                "description": "Up to 25 seats",
            }
        }
    )

    product_id: UUID
    sku: Sku
    name: DisplayName
    description: Description = None


class VariantUpdate(BaseModel):
    """`product_id` is immutable: variants cannot be moved between products."""

    sku: Sku | None = None
    name: DisplayName | None = None
    description: Description = None
    is_active: StrictBool | None = None

    @model_validator(mode="after")
    def _check_patch(self) -> "VariantUpdate":
        _validate_patch(self, ("sku", "name", "is_active"))
        return self


class VariantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    sku: str
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PaginatedProducts(BaseModel):
    items: list[ProductResponse]
    total: int = Field(description="Total matching products, before pagination.")
    limit: int
    offset: int


class PaginatedVariants(BaseModel):
    items: list[VariantResponse]
    total: int = Field(description="Total matching variants, before pagination.")
    limit: int
    offset: int


def model_dump_patch(model: BaseModel) -> dict[str, Any]:
    """Return only the fields the client explicitly sent."""
    return model.model_dump(exclude_unset=True)
