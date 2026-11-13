"""Integer-rupee money helpers.

Platform rule (as of migration 004): money is stored as a whole number of
rupees. Sub-rupee amounts are not representable, so every calculation that
could produce one (tax, proration, discounts) must define its rounding policy.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

# Sanity ceiling (₹10 trillion). Keeps arithmetic far below PostgreSQL bigint
# overflow (9.22 * 10^18).
MAX_RUPEES = 10**13

# Reusable Pydantic type: strict integer, 0 <= value <= MAX_RUPEES.
# Strict mode rejects floats ("2999.0"), numeric strings ("2999") and bools.
Rupees = Annotated[
    int,
    Field(
        strict=True,
        ge=0,
        le=MAX_RUPEES,
        description="Amount in whole rupees (integer). Sub-rupee values are rejected.",
    ),
]
