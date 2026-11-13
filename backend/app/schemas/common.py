"""Reusable validated field types shared by catalog schemas."""

from __future__ import annotations

from typing import Annotated

from pydantic import BeforeValidator, Field, StringConstraints


def _normalise_sku(value: object) -> object:
    if isinstance(value, str):
        return value.strip().upper()
    return value


def _collapse_whitespace(value: object) -> object:
    if isinstance(value, str):
        return " ".join(value.split())
    return value


def _clean_description(value: object) -> object:
    if isinstance(value, str):
        return value.strip() or None
    return value


# Uppercase SKU: letters, digits, hyphen, underscore. Stored uppercase.
Sku = Annotated[
    str,
    BeforeValidator(_normalise_sku),
    StringConstraints(
        min_length=2,
        max_length=32,
        pattern=r"^[A-Z0-9][A-Z0-9_-]+$",
    ),
    Field(description="SKU (2-32 chars): A-Z, 0-9, '-' or '_'. Normalised to uppercase."),
]

# Human-readable resource name; internal whitespace is collapsed.
DisplayName = Annotated[
    str,
    BeforeValidator(_collapse_whitespace),
    StringConstraints(min_length=2, max_length=120),
]

Description = Annotated[
    str | None,
    BeforeValidator(_clean_description),
    Field(max_length=2000, description="Optional free-text description."),
]

StrictBool = Annotated[bool, Field(strict=True)]
