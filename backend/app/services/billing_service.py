"""Brightloop Billing Engine & Subscription Service.

Implements recurring subscription lifecycle, quotation conversion,
automated billing runs (Billing Day), tax calculation, discount rules,
invoice lifecycle, payment recording, and finance reports.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from app.core.database import get_supabase
from app.core.security import hash_password
from app.schemas.subscription import (
    BillingRunRequest,
    BillingRunResult,
    DashboardMetrics,
    InvoiceResponse,
    PaymentCreate,
    PaymentResponse,
    SubscriptionCreate,
    SubscriptionResponse,
    SubscriptionStatus,
)
from app.services import plan_service, product_service, store

logger = logging.getLogger(__name__)


def _add_interval(start: date, interval: str, count: int = 1) -> date:
    """Advance a date by plan intervals."""
    if interval == "day":
        return start + timedelta(days=count)
    elif interval == "week":
        return start + timedelta(weeks=count)
    elif interval == "month":
        # approximate month advance
        month = start.month - 1 + count
        year = start.year + month // 12
        month = month % 12 + 1
        day = min(start.day, 28)  # safe day clamp
        return date(year, month, day)
    elif interval == "year":
        try:
            return start.replace(year=start.year + count)
        except ValueError:
            return start.replace(year=start.year + count, day=28)
    return start + timedelta(days=30 * count)


def _due_date_for_terms(issue_date: date, terms: str) -> date:
    if terms == "net15":
        return issue_date + timedelta(days=15)
    elif terms == "net30":
        return issue_date + timedelta(days=30)
    elif terms == "net60":
        return issue_date + timedelta(days=60)
    return issue_date  # immediate


# --------------------------------------------------------------------------- #
# Quotation Templates
# --------------------------------------------------------------------------- #


def create_subscription_from_template(template_id: str, customer_id: str) -> dict[str, Any]:
    tpl = store.get_quotation_template_by_id(template_id)
    if not tpl:
        raise ValueError("Quotation template not found.")

    valid_days = tpl.get("valid_days", 30)
    today = date.today()
    expiry = today + timedelta(days=valid_days)

    lines_data = []
    for line in tpl.get("lines", []):
        tax_rate = 0.0
        if line.get("tax_id"):
            tax = store.get_tax_by_id(line["tax_id"])
            if tax:
                tax_rate = tax.get("rate", 0.0)
        lines_data.append({
            "product_id": line["product_id"],
            "variant_id": line.get("variant_id"),
            "quantity": line.get("quantity", 1),
            "unit_price": line.get("unit_price", 0),
            "tax_id": line.get("tax_id"),
            "tax_rate": tax_rate,
            "amount": int(line.get("quantity", 1)) * int(line.get("unit_price", 0)),
        })

    sub_data = {
        "customer_id": customer_id,
        "plan_id": tpl.get("plan_id"),
        "status": SubscriptionStatus.quotation.value,
        "start_date": today,
        "expiry_date": expiry,
        "payment_terms": "net30",
        "notes": f"Generated from template: {tpl.get('name')}",
    }

    return store.create_subscription(sub_data, lines_data)


# --------------------------------------------------------------------------- #
# Subscriptions
# --------------------------------------------------------------------------- #


def create_subscription(payload: SubscriptionCreate) -> dict[str, Any]:
    today = payload.start_date or date.today()
    lines_data = []
    for l in payload.lines:
        tax_rate = 0.0
        if l.tax_id:
            tax = store.get_tax_by_id(l.tax_id)
            if tax:
                tax_rate = tax.get("rate", 0.0)
        lines_data.append({
            "product_id": str(l.product_id),
            "variant_id": str(l.variant_id) if l.variant_id else None,
            "quantity": l.quantity,
            "unit_price": l.unit_price,
            "tax_id": str(l.tax_id) if l.tax_id else None,
            "tax_rate": tax_rate,
            "amount": l.quantity * l.unit_price,
        })

    sub_data = {
        "customer_id": str(payload.customer_id),
        "plan_id": str(payload.plan_id),
        "status": payload.status.value,
        "start_date": today,
        "expiry_date": payload.expiry_date,
        "payment_terms": payload.payment_terms.value,
        "next_billing_date": today,
        "auto_close": payload.auto_close,
        "discount_id": str(payload.discount_id) if payload.discount_id else None,
        "notes": payload.notes,
    }

    return store.create_subscription(sub_data, lines_data)


def transition_subscription(subscription_id: str, target_status: SubscriptionStatus) -> dict[str, Any]:
    sub = store.get_subscription_by_id(subscription_id)
    if not sub:
        raise ValueError("Subscription not found.")

    current = sub.get("status")
    allowed_transitions = {
        "draft": ["quotation", "confirmed", "closed"],
        "quotation": ["confirmed", "closed"],
        "confirmed": ["active", "closed"],
        "active": ["paused", "closed"],
        "paused": ["active", "closed"],
        "closed": ["draft"],  # can recreate/reopen as draft
    }

    if target_status.value not in allowed_transitions.get(current, []):
        raise ValueError(f"Cannot transition from {current} to {target_status.value}.")

    updates: dict[str, Any] = {"status": target_status.value}
    if target_status == SubscriptionStatus.active and not sub.get("next_billing_date"):
        updates["next_billing_date"] = sub.get("start_date", date.today().isoformat())

    updated = store.update_subscription(subscription_id, updates)
    return updated or sub


def renew_subscription(subscription_id: str, additional_months: int = 12) -> dict[str, Any]:
    sub = store.get_subscription_by_id(subscription_id)
    if not sub:
        raise ValueError("Subscription not found.")

    current_expiry = date.today()
    if sub.get("expiry_date"):
        try:
            current_expiry = date.fromisoformat(sub["expiry_date"])
        except Exception:
            pass

    new_expiry = _add_interval(current_expiry, "month", additional_months)
    updates = {
        "expiry_date": new_expiry.isoformat(),
        "status": SubscriptionStatus.active.value,
        "next_billing_date": date.today().isoformat(),
    }
    return store.update_subscription(subscription_id, updates) or sub


# --------------------------------------------------------------------------- #
# Automated Billing Run ("Billing Day")
# --------------------------------------------------------------------------- #


def run_billing_day(request: BillingRunRequest) -> BillingRunResult:
    """Evaluates all active subscriptions and generates due invoices.

    Guarantees:
    - Automatically populates customer details, lines, taxes, and totals.
    - Idempotent: Never double-bills for the same subscription period.
    - Evaluates discount rules automatically.
    - Calculates payment terms and due dates.
    - Advances next_billing_date for subsequent billing periods.
    """
    target_date = request.billing_date or date.today()
    subs = store.get_subscriptions(customer_id=str(request.customer_id) if request.customer_id else None)

    active_subs = [s for s in subs if s.get("status") == "active"]
    billed_periods = {
        (inv["subscription_id"], str(inv["billing_period_start"]))
        for inv in store.get_invoices()
        if inv.get("subscription_id") and inv.get("status") != "cancelled"
    }
    processed = 0
    invoices_created = 0
    skipped = 0
    total_billed = 0
    created_invoices: list[InvoiceResponse] = []

    for sub in active_subs:
        processed += 1
        sub_id = sub["id"]
        next_billing_str = sub.get("next_billing_date") or sub.get("start_date")
        if not next_billing_str:
            skipped += 1
            continue

        try:
            next_billing = date.fromisoformat(next_billing_str)
        except Exception:
            skipped += 1
            continue

        if next_billing > target_date:
            skipped += 1
            continue

        plan = store.get_plan_by_id(sub["plan_id"]) if sub.get("plan_id") else None

        interval = plan.get("billing_interval", "month") if plan else "month"
        interval_count = plan.get("interval_count", 1) if plan else 1
        period_start = next_billing
        period_end = _add_interval(period_start, interval, interval_count)

        # Idempotency check: skip if a live invoice already covers this period
        if (sub_id, period_start.isoformat()) in billed_periods:
            skipped += 1
            continue

        # Prepare invoice lines
        inv_lines = []
        subtotal = 0
        tax_total = 0

        sub_lines = sub.get("subscription_lines", [])
        if not sub_lines:
            # Fallback to plan price if no explicit lines
            base_price = plan.get("price_inr", 0) if plan else 0
            plan_name = plan.get("name", "Subscription Plan") if plan else "Subscription Plan"
            inv_lines.append({
                "product_id": None,
                "description": f"{plan_name} ({period_start.isoformat()} to {period_end.isoformat()})",
                "quantity": 1,
                "unit_price": base_price,
                "tax_rate": 18.0,
                "tax_amount": int(round(base_price * 0.18)),
                "discount_amount": 0,
                "total_amount": base_price + int(round(base_price * 0.18)),
            })
            subtotal += base_price
            tax_total += int(round(base_price * 0.18))
        else:
            for sl in sub_lines:
                qty = sl.get("quantity", 1)
                unit_price = sl.get("unit_price", 0)
                line_subtotal = qty * unit_price
                t_rate = float(sl.get("tax_rate", 0))
                t_amt = int(round(line_subtotal * (t_rate / 100.0)))
                line_desc = sl.get("product_name") or "Subscription Line"
                if sl.get("variant_name"):
                    line_desc += f" - {sl['variant_name']}"

                inv_lines.append({
                    "product_id": sl.get("product_id"),
                    "description": line_desc,
                    "quantity": qty,
                    "unit_price": unit_price,
                    "tax_rate": t_rate,
                    "tax_amount": t_amt,
                    "discount_amount": 0,
                    "total_amount": line_subtotal + t_amt,
                })
                subtotal += line_subtotal
                tax_total += t_amt

        # Discount evaluation
        discount_total = 0
        discount_id = sub.get("discount_id")
        if discount_id:
            disc = store.get_discount_by_id(discount_id)
            if disc and disc.get("is_active"):
                valid = True
                now_str = datetime.utcnow().isoformat()
                if disc.get("start_date") and disc["start_date"] > now_str:
                    valid = False
                if disc.get("end_date") and disc["end_date"] < now_str:
                    valid = False
                if disc.get("max_uses") and (disc.get("used_count", 0) >= disc["max_uses"]):
                    valid = False
                if subtotal < disc.get("min_purchase_amount", 0):
                    valid = False

                if valid:
                    if disc.get("discount_type") == "percentage":
                        discount_total = int(round(subtotal * (disc.get("discount_value", 0) / 100.0)))
                    else:
                        discount_total = min(subtotal, int(disc.get("discount_value", 0)))
                    store.increment_discount_used_count(discount_id)

        inv_total = max(0, subtotal + tax_total - discount_total)
        terms = sub.get("payment_terms", "immediate")
        due_date = _due_date_for_terms(target_date, terms)

        inv_data = {
            "subscription_id": sub_id,
            "customer_id": sub["customer_id"],
            "status": "confirmed",
            "subtotal": subtotal,
            "tax_total": tax_total,
            "discount_total": discount_total,
            "total_amount": inv_total,
            "amount_paid": 0,
            "billing_period_start": period_start,
            "billing_period_end": period_end,
            "issue_date": target_date,
            "due_date": due_date,
            "notes": f"Recurring invoice for period {period_start} to {period_end}",
        }

        if not request.dry_run:
            inv = store.create_invoice(inv_data, inv_lines)
            invoices_created += 1
            total_billed += inv_total
            created_invoices.append(InvoiceResponse.model_validate(inv))
            billed_periods.add((sub_id, period_start.isoformat()))

            # Advance subscription next_billing_date
            next_next = period_end
            sub_updates: dict[str, Any] = {
                "next_billing_date": next_next.isoformat(),
                "last_billed_date": target_date.isoformat(),
            }
            # Auto-close check if plan/subscription auto_close is enabled
            if sub.get("auto_close") and sub.get("expiry_date"):
                if sub["expiry_date"] <= target_date.isoformat():
                    sub_updates["status"] = "closed"

            store.update_subscription(sub_id, sub_updates)
        else:
            invoices_created += 1
            total_billed += inv_total

    return BillingRunResult(
        processed_count=processed,
        invoices_created=invoices_created,
        skipped_count=skipped,
        total_billed=total_billed,
        invoices=created_invoices,
    )


# --------------------------------------------------------------------------- #
# Payments
# --------------------------------------------------------------------------- #


def record_payment(payload: PaymentCreate) -> dict[str, Any]:
    inv = store.get_invoice_by_id(payload.invoice_id)
    if not inv:
        raise ValueError("Invoice not found.")

    if inv.get("status") == "cancelled":
        raise ValueError("Cannot pay a cancelled invoice.")

    payment_record = {
        "invoice_id": str(payload.invoice_id),
        "amount": payload.amount,
        "payment_method": payload.payment_method.value,
        "payment_date": payload.payment_date,
        "note": payload.note,
    }
    return store.create_payment(payment_record)


# --------------------------------------------------------------------------- #
# Dashboard & Reports
# --------------------------------------------------------------------------- #


def get_dashboard_metrics() -> DashboardMetrics:
    subs = store.get_subscriptions()
    invoices = store.get_invoices()
    payments = store.get_payments()

    active_subs = [s for s in subs if s.get("status") == "active"]
    total_revenue = sum(p.get("amount", 0) for p in payments)
    total_outstanding = sum(inv.get("balance_due", 0) for inv in invoices if inv.get("status") == "confirmed")
    overdue_invoices = [inv for inv in invoices if inv.get("is_overdue")]
    overdue_amount = sum(inv.get("balance_due", 0) for inv in overdue_invoices)

    # Monthly recurring revenue: each active subscription's recurring amount
    # (its lines, or the plan price when it has none) normalised to one month.
    plans = {p["id"]: p for p in store._fetch_in("plans", "id", (s["plan_id"] for s in active_subs))}
    mrr = 0.0
    for s in active_subs:
        plan = plans.get(s["plan_id"]) or {}
        amount = s.get("total_recurring_amount") or plan.get("price_inr") or 0
        count = max(1, int(plan.get("interval_count") or 1))
        per_month = {"day": 30.0, "week": 52 / 12, "month": 1.0, "year": 1 / 12}.get(plan.get("billing_interval", "month"), 1.0)
        mrr += amount * per_month / count
    mrr = int(round(mrr))
    arr = mrr * 12

    total_customers = store.count_customers()

    recent_invs = [InvoiceResponse.model_validate(inv) for inv in invoices[:8]]
    recent_pays = [PaymentResponse.model_validate(p) for p in payments[:8]]
    overdue_invs = [InvoiceResponse.model_validate(inv) for inv in overdue_invoices[:8]]

    return DashboardMetrics(
        active_subscriptions=len(active_subs),
        total_revenue_collected=total_revenue,
        total_outstanding=total_outstanding,
        overdue_invoices_count=len(overdue_invoices),
        overdue_amount=overdue_amount,
        monthly_recurring_revenue=mrr,
        annual_run_rate=arr,
        total_customers=total_customers,
        total_invoices=len(invoices),
        recent_invoices=recent_invs,
        recent_payments=recent_pays,
        overdue_invoices=overdue_invs,
    )


# --------------------------------------------------------------------------- #
# Printable Invoice HTML Generator
# --------------------------------------------------------------------------- #


def generate_printable_invoice_html(invoice_id: str) -> str:
    inv = store.get_invoice_by_id(invoice_id)
    if not inv:
        return "<h1>Invoice not found</h1>"

    lines_html = ""
    for idx, l in enumerate(inv.get("lines", []), 1):
        lines_html += f"""
        <tr>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; text-align: center;">{idx}</td>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{l.get('description')}</td>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; text-align: center;">{l.get('quantity')}</td>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; text-align: right;">₹{l.get('unit_price'):,}</td>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; text-align: right;">{l.get('tax_rate')}%</td>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; text-align: right; font-weight: 600;">₹{l.get('total_amount'):,}</td>
        </tr>
        """

    status_badge_color = {
        "paid": "#16a34a",
        "confirmed": "#2563eb",
        "draft": "#64748b",
        "cancelled": "#dc2626",
    }.get(inv.get("status"), "#64748b")

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8" />
    <title>Invoice {inv.get('invoice_number')} - Brightloop Software</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 40px; color: #1e293b; background: #f8fafc; }}
        .invoice-box {{ max-width: 800px; margin: auto; padding: 30px; border: 1px solid #e2e8f0; background: #ffffff; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }}
        .header {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 30px; }}
        .logo-box {{ font-size: 26px; font-weight: 800; color: #7c3aed; letter-spacing: -0.5px; }}
        .badge {{ display: inline-block; padding: 4px 12px; border-radius: 9999px; font-size: 13px; font-weight: 700; text-transform: uppercase; color: #ffffff; background: {status_badge_color}; }}
        .meta-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 30px; font-size: 14px; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 30px; font-size: 14px; }}
        th {{ background: #f1f5f9; padding: 10px; text-align: left; font-weight: 600; color: #475569; }}
        .summary {{ margin-left: auto; width: 300px; font-size: 14px; }}
        .summary-row {{ display: flex; justify-content: space-between; padding: 6px 0; }}
        .total-row {{ display: flex; justify-content: space-between; padding: 10px 0; font-size: 18px; font-weight: 800; border-top: 2px solid #e2e8f0; color: #7c3aed; }}
        .actions {{ margin-top: 30px; text-align: center; }}
        .print-btn {{ background: #7c3aed; color: #fff; border: none; padding: 10px 24px; font-size: 14px; font-weight: 600; border-radius: 6px; cursor: pointer; }}
        @media print {{ .actions {{ display: none; }} body {{ background: #fff; padding: 0; }} .invoice-box {{ border: none; box-shadow: none; }} }}
    </style>
</head>
<body>
    <div class="invoice-box">
        <div class="header">
            <div>
                <div class="logo-box">Brightloop.</div>
                <div style="color: #64748b; font-size: 13px; margin-top: 4px;">Brightloop Software Private Limited</div>
                <div style="color: #64748b; font-size: 13px;">Bengaluru, Karnataka, India</div>
                <div style="color: #64748b; font-size: 13px;">GSTIN: 29AAAAA0000A1Z5</div>
            </div>
            <div style="text-align: right;">
                <div style="font-size: 22px; font-weight: 800; color: #0f172a;">TAX INVOICE</div>
                <div style="font-size: 14px; color: #64748b; margin-top: 4px;">Invoice #: <strong>{inv.get('invoice_number')}</strong></div>
                <div style="margin-top: 6px;"><span class="badge">{inv.get('status')}</span></div>
            </div>
        </div>

        <div class="meta-grid">
            <div>
                <strong style="color: #475569;">Billed To:</strong>
                <div style="font-size: 16px; font-weight: 700; margin-top: 4px;">{inv.get('customer_name', 'Customer')}</div>
                <div style="color: #64748b;">{inv.get('customer_email', '')}</div>
                {f'<div style="color: #64748b; margin-top: 4px;">Subscription Ref: {inv.get("subscription_number")}</div>' if inv.get("subscription_number") else ''}
            </div>
            <div style="text-align: right;">
                <div><span style="color: #64748b;">Issue Date:</span> <strong>{inv.get('issue_date')}</strong></div>
                <div style="margin-top: 4px;"><span style="color: #64748b;">Due Date:</span> <strong>{inv.get('due_date')}</strong></div>
                {f'<div style="margin-top: 4px;"><span style="color: #64748b;">Period:</span> {inv.get("billing_period_start")} to {inv.get("billing_period_end")}</div>' if inv.get("billing_period_start") else ''}
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    <th style="width: 40px; text-align: center;">#</th>
                    <th>Description</th>
                    <th style="width: 60px; text-align: center;">Qty</th>
                    <th style="width: 100px; text-align: right;">Unit Price</th>
                    <th style="width: 80px; text-align: right;">Tax</th>
                    <th style="width: 120px; text-align: right;">Amount</th>
                </tr>
            </thead>
            <tbody>
                {lines_html}
            </tbody>
        </table>

        <div class="summary">
            <div class="summary-row">
                <span style="color: #64748b;">Subtotal:</span>
                <span>₹{inv.get('subtotal', 0):,}</span>
            </div>
            <div class="summary-row">
                <span style="color: #64748b;">Tax Total:</span>
                <span>₹{inv.get('tax_total', 0):,}</span>
            </div>
            {f'<div class="summary-row" style="color: #16a34a;"><span>Discount:</span><span>-₹{inv.get("discount_total", 0):,}</span></div>' if inv.get("discount_total") else ''}
            <div class="total-row">
                <span>Total Amount:</span>
                <span>₹{inv.get('total_amount', 0):,}</span>
            </div>
            <div class="summary-row" style="font-weight: 600;">
                <span style="color: #64748b;">Amount Paid:</span>
                <span>₹{inv.get('amount_paid', 0):,}</span>
            </div>
            <div class="summary-row" style="font-size: 15px; font-weight: 700; color: {'#dc2626' if inv.get('balance_due', 0) > 0 else '#16a34a'};">
                <span>Balance Due:</span>
                <span>₹{inv.get('balance_due', 0):,}</span>
            </div>
        </div>

        <div class="actions">
            <button class="print-btn" onclick="window.print()">Print / Save as PDF</button>
        </div>
    </div>
</body>
</html>"""
    return html


# --------------------------------------------------------------------------- #
# Realistic Brightloop Demo Data Seeder
# --------------------------------------------------------------------------- #


def seed_demo_data() -> dict[str, Any]:
    """Populate Supabase with a realistic demo dataset.

    Replaces the catalog and billing rows (products, plans, taxes, discounts,
    templates, subscriptions, invoices, payments). Users are never deleted and
    existing accounts keep their passwords: a demo account is only created when
    its email is not registered yet.
    """
    sb = get_supabase()
    store.clear_business_data()

    today = date.today()

    # 1. Users (create only the missing demo accounts)
    demo_users = [
        ("arjun@brightloop.in", "Arjun Nair", "admin", "Admin@2026"),
        ("priya@brightloop.in", "Priya Sharma", "staff", "Staff@2026"),
        ("contact@technova.io", "TechNova Solutions", "customer", "Customer@2026"),
        ("finance@greenleaf.com", "GreenLeaf Organics", "customer", "Customer@2026"),
        ("ops@apexdigital.in", "Apex Digital Works", "customer", "Customer@2026"),
    ]
    existing = {
        u["email"]: u
        for u in sb.table("users").select("id,email").in_("email", [u[0] for u in demo_users]).execute().data or []
    }
    created_users = []
    for email, name, role, password in demo_users:
        if email in existing:
            continue
        row = (
            sb.table("users")
            .insert({"email": email, "name": name, "role": role, "password_hash": hash_password(password)})
            .execute()
            .data[0]
        )
        existing[email] = row
        created_users.append(email)
    cust1_id = existing["contact@technova.io"]["id"]
    cust2_id = existing["finance@greenleaf.com"]["id"]
    cust3_id = existing["ops@apexdigital.in"]["id"]

    # 2. Taxes
    t1 = store.create_tax("GST 18%", 18.0)
    store.create_tax("VAT 5%", 5.0)
    store.create_tax("Zero Tax 0%", 0.0)

    # 3. Products & variants
    def insert(table: str, row: dict[str, Any]) -> dict[str, Any]:
        return sb.table(table).insert(row).execute().data[0]

    def product(sku: str, name: str, desc: str, ptype: str, sales: int, cost: int, notes: str) -> str:
        return insert("products", {
            "sku": sku, "name": name, "description": desc, "product_type": ptype,
            "sales_price": sales, "cost_price": cost, "notes": notes,
        })["id"]

    def variant(pid: str, sku: str, name: str, desc: str, attr: str, value: str, extra: int) -> str:
        return insert("product_variants", {
            "product_id": pid, "sku": sku, "name": name, "description": desc,
            "attribute_name": attr, "attribute_value": value, "price_extra": extra,
        })["id"]

    def plan(vid: str, name: str, interval: str, price: int, trial: int, auto_close: bool = False) -> str:
        return insert("plans", {
            "variant_id": vid, "name": name, "billing_interval": interval, "interval_count": 1,
            "price_inr": price, "currency": "INR", "trial_days": trial, "auto_close": auto_close,
        })["id"]

    p_crm = product("BL-CRM", "Brightloop CRM", "Cloud Customer Relationship Management suite", "software", 2499, 500, "Core business product")
    p_erp = product("BL-ERP", "Brightloop ERP", "Enterprise resource planning and multi-currency billing", "software", 4999, 1200, "Flagship enterprise edition")
    p_ai = product("BL-AI-ADDON", "AI Copilot Add-on", "Predictive churn analytics and smart lead scoring", "addon", 799, 150, "Monthly recurring add-on")

    v_crm_std = variant(p_crm, "BL-CRM-STD", "Standard Edition", "Up to 15 team seats", "Edition", "Standard", 0)
    variant(p_crm, "BL-CRM-ENT", "Enterprise Dedicated", "Unlimited team seats & dedicated support", "Edition", "Enterprise", 1500)
    # Problem statement: "choosing the Odoo brand adds 560 to the price"
    v_erp_odoo = variant(p_erp, "BL-ERP-ODOO", "Odoo Brand Edition", "Integrated Odoo connectors and syncing", "Brand", "Odoo", 560)
    v_ai_std = variant(p_ai, "BL-AI-STD", "Standard AI Add-on", "50,000 monthly inference tokens", "Tier", "Standard", 0)

    # 4. Plans
    plan_crm_monthly = plan(v_crm_std, "CRM Standard Monthly", "month", 2499, 14)
    plan_crm_yearly = plan(v_crm_std, "CRM Standard Yearly", "year", 24990, 0)
    plan_erp_odoo = plan(v_erp_odoo, "Odoo ERP Suite Monthly", "month", 5559, 7)
    plan(v_ai_std, "AI Copilot Monthly", "month", 799, 0, auto_close=True)

    # 5. Discounts
    store.create_discount({
        "code": "STARTUP20", "description": "20% off whole subscription for growing startups",
        "discount_type": "percentage", "discount_value": 20.0, "min_purchase_amount": 4000,
        "min_quantity": 2, "max_uses": 50, "applies_to": "whole_subscription",
    })
    store.create_discount({
        "code": "FLAT500", "description": "₹500 flat discount on CRM subscriptions",
        "discount_type": "fixed", "discount_value": 500.0, "min_purchase_amount": 2000,
        "max_uses": 100, "applies_to": "whole_subscription",
    })

    # 6. Quotation templates
    store.create_quotation_template({
        "name": "High-Growth CRM Suite",
        "description": "Pre-configured offer with 5 Standard CRM seats and AI Copilot",
        "plan_id": plan_crm_monthly, "valid_days": 30,
        "lines": [
            {"product_id": p_crm, "variant_id": v_crm_std, "quantity": 5, "unit_price": 2499, "tax_id": t1["id"]},
            {"product_id": p_ai, "variant_id": v_ai_std, "quantity": 1, "unit_price": 799, "tax_id": t1["id"]},
        ],
    })
    store.create_quotation_template({
        "name": "Odoo Integrated Enterprise Package",
        "description": "Enterprise Odoo ERP setup with Net 30 terms",
        "plan_id": plan_erp_odoo, "valid_days": 15,
        "lines": [{"product_id": p_erp, "variant_id": v_erp_odoo, "quantity": 10, "unit_price": 5559, "tax_id": t1["id"]}],
    })

    # 7. Subscriptions
    sub1 = store.create_subscription({
        "customer_id": cust1_id, "plan_id": plan_crm_monthly, "status": "active",
        "start_date": today - timedelta(days=30), "expiry_date": today + timedelta(days=335),
        "payment_terms": "net15", "next_billing_date": today,  # due for billing today
        "notes": "TechNova primary CRM subscription",
    }, [
        {"product_id": p_crm, "variant_id": v_crm_std, "quantity": 3, "unit_price": 2499, "tax_id": t1["id"], "tax_rate": 18.0},
        {"product_id": p_ai, "variant_id": v_ai_std, "quantity": 1, "unit_price": 799, "tax_id": t1["id"], "tax_rate": 18.0},
    ])
    sub2 = store.create_subscription({
        "customer_id": cust2_id, "plan_id": plan_erp_odoo, "status": "active",
        "start_date": today - timedelta(days=60), "expiry_date": today + timedelta(days=305),
        "payment_terms": "net30", "next_billing_date": today + timedelta(days=25),
        "notes": "GreenLeaf Retailers Odoo ERP Suite",
    }, [
        {"product_id": p_erp, "variant_id": v_erp_odoo, "quantity": 2, "unit_price": 5559, "tax_id": t1["id"], "tax_rate": 18.0},
    ])
    sub3 = store.create_subscription({
        "customer_id": cust3_id, "plan_id": plan_crm_yearly, "status": "quotation",
        "start_date": today, "expiry_date": today + timedelta(days=21),
        "payment_terms": "net30", "next_billing_date": today,
        "notes": "Yearly contract quote under review",
    }, [
        {"product_id": p_crm, "variant_id": v_crm_std, "quantity": 8, "unit_price": 24990, "tax_id": t1["id"], "tax_rate": 18.0},
    ])

    # 8. Invoices & payments. Invoices start with amount_paid=0: create_payment
    # adds each payment to the invoice (and marks it paid when fully covered).
    inv1 = store.create_invoice({
        "subscription_id": sub2["id"], "customer_id": cust2_id, "status": "confirmed",
        "subtotal": 11118, "tax_total": 2001, "discount_total": 0, "total_amount": 13119,
        "billing_period_start": today - timedelta(days=60), "billing_period_end": today - timedelta(days=30),
        "issue_date": today - timedelta(days=60), "due_date": today - timedelta(days=30),
        "notes": "Paid promptly via UPI",
    }, [
        {"product_id": p_erp, "description": "Odoo Brand Edition (2 seats)", "quantity": 2, "unit_price": 5559,
         "tax_rate": 18.0, "tax_amount": 2001, "total_amount": 13119},
    ])
    store.create_payment({
        "invoice_id": inv1["id"], "amount": 13119, "payment_method": "upi",
        "payment_date": today - timedelta(days=45), "note": "UPI transaction ref: UPI/2026/049182",
    })

    store.create_invoice({
        "subscription_id": sub3["id"], "customer_id": cust3_id, "status": "confirmed",
        "subtotal": 8000, "tax_total": 1440, "discount_total": 500, "total_amount": 8940,
        "billing_period_start": today - timedelta(days=40), "billing_period_end": today - timedelta(days=10),
        "issue_date": today - timedelta(days=40), "due_date": today - timedelta(days=10),  # overdue
        "notes": "Pending payment - follow up required",
    }, [
        {"product_id": p_crm, "description": "Brightloop CRM Pilot Setup", "quantity": 1, "unit_price": 8000,
         "tax_rate": 18.0, "tax_amount": 1440, "discount_amount": 500, "total_amount": 8940},
    ])

    inv3 = store.create_invoice({
        "subscription_id": sub1["id"], "customer_id": cust1_id, "status": "confirmed",
        "subtotal": 8296, "tax_total": 1493, "discount_total": 0, "total_amount": 9789,
        "billing_period_start": today - timedelta(days=30), "billing_period_end": today,
        "issue_date": today - timedelta(days=15), "due_date": today + timedelta(days=15),
        "notes": "Partial advance paid",
    }, [
        {"product_id": p_crm, "description": "TechNova Standard CRM & AI", "quantity": 1, "unit_price": 8296,
         "tax_rate": 18.0, "tax_amount": 1493, "total_amount": 9789},
    ])
    store.create_payment({
        "invoice_id": inv3["id"], "amount": 4000, "payment_method": "bank_transfer",
        "payment_date": today - timedelta(days=10), "note": "NEFT transfer from HDFC account",
    })

    return {
        "status": "success",
        "message": "Demo data successfully seeded for Brightloop Software!",
        "demo_accounts_created": created_users,
        "demo_accounts_already_existed": [u[0] for u in demo_users if u[0] not in created_users],
        "note": "Existing accounts keep their current passwords.",
    }
