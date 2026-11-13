"""Hard-delete smoke-test rows created by backend/scripts/live_smoke.ps1.

Uses the same Supabase client configuration as the API, so it exercises the
same credentials without duplicating REST header logic in PowerShell.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# backend/ (scripts -> backend)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from postgrest.exceptions import APIError  # noqa: E402
from supabase import Client  # noqa: E402

from app.core.database import get_supabase  # noqa: E402

MISSING_TABLE_CODES = {"42P01", "PGRST205"}


def delete_rows(client: Client, table: str, column: str, pattern: str) -> None:
    """Delete matching rows, tolerating a table that is not migrated yet."""
    try:
        client.table(table).delete().like(column, pattern).execute()
    except APIError as exc:
        if getattr(exc, "code", None) in MISSING_TABLE_CODES:
            return
        raise


def main() -> int:
    """Delete all rows belonging to one smoke suffix."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suffix", required=True, help="Smoke suffix, e.g. 20261031A")
    args = parser.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9]{1,17}", args.suffix):
        parser.error("--suffix must be 1-17 alphanumeric characters")

    suffix = args.suffix.upper()
    run = f"SMOKE-{suffix}"
    email_prefix = f"smoke.{suffix.lower()}."

    client = get_supabase()

    # Children first; the FKs are ON DELETE RESTRICT.
    delete_rows(client, "plans", "name", f"{run}%")
    delete_rows(client, "product_variants", "sku", f"{run}-%")
    delete_rows(client, "products", "sku", f"{run}-%")
    delete_rows(client, "users", "email", f"{email_prefix}%")

    print(f"cleanup ok: {run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
