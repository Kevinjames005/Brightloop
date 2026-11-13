"""Access-control tests for the billing endpoints.

These run entirely in memory: the database layer is replaced with small fakes, so no
Supabase project, network or .env file is needed. Run them from backend/ with `pytest`.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import billing as billing_endpoints
from app.core.dependencies import get_current_user
from app.main import app
from app.services import billing_service, store

OWNER_ID = str(uuid4())
OTHER_ID = str(uuid4())
STAFF_ID = str(uuid4())
PLAN_ID = str(uuid4())


def make_user(user_id: str, role: str) -> dict:
    return {"id": user_id, "role": role, "email": f"{role}@example.com", "name": role.title(), "is_active": True, "token_version": 0}


OWNER = make_user(OWNER_ID, "customer")
OTHER = make_user(OTHER_ID, "customer")
STAFF = make_user(STAFF_ID, "staff")


def make_subscription(customer_id: str, status: str = "active") -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(uuid4()), "subscription_number": "SUB-2026-0001", "customer_id": customer_id, "plan_id": PLAN_ID,
        "status": status, "start_date": date.today().isoformat(), "expiry_date": None, "payment_terms": "immediate",
        "next_billing_date": date.today().isoformat(), "last_billed_date": None, "auto_close": False,
        "discount_id": None, "notes": None, "created_at": now, "updated_at": now,
    }


@pytest.fixture()
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def act_as(client):
    def _act_as(user: dict) -> TestClient:
        app.dependency_overrides[get_current_user] = lambda: user
        return client
    return _act_as


@pytest.fixture()
def subs(monkeypatch):
    """A fake subscription store plus recorders for the state-changing service calls."""
    rows: dict[str, dict] = {}
    calls = SimpleNamespace(transitions=[], renewals=[], created=[])

    monkeypatch.setattr(store, "get_subscription_by_id", lambda sid: rows.get(str(sid)))

    def transition(sid, target):
        calls.transitions.append((str(sid), target.value))
        return rows[str(sid)]

    def renew(sid, additional_months=12):
        calls.renewals.append(str(sid))
        return rows[str(sid)]

    def create(payload):
        calls.created.append(payload)
        return make_subscription(str(payload.customer_id), status=payload.status.value)

    monkeypatch.setattr(billing_service, "transition_subscription", transition)
    monkeypatch.setattr(billing_service, "renew_subscription", renew)
    monkeypatch.setattr(billing_service, "create_subscription", create)
    return SimpleNamespace(rows=rows, calls=calls)


ACTIONS = ["to-quotation", "confirm", "pause", "resume", "close"]


@pytest.mark.parametrize("action", ACTIONS + ["renew"])
def test_customer_cannot_act_on_someone_elses_subscription(act_as, subs, action):
    sub = make_subscription(OTHER_ID)
    subs.rows[sub["id"]] = sub

    response = act_as(OWNER).post(f"/api/v1/subscriptions/{sub['id']}/{action}")

    assert response.status_code == 403
    assert subs.calls.transitions == [] and subs.calls.renewals == []


@pytest.mark.parametrize("action", ACTIONS)
def test_customer_can_act_on_their_own_subscription(act_as, subs, action):
    sub = make_subscription(OWNER_ID)
    subs.rows[sub["id"]] = sub

    response = act_as(OWNER).post(f"/api/v1/subscriptions/{sub['id']}/{action}")

    assert response.status_code == 200
    assert len(subs.calls.transitions) == 1


@pytest.mark.parametrize("action", ACTIONS)
def test_staff_can_act_on_any_subscription(act_as, subs, action):
    sub = make_subscription(OTHER_ID)
    subs.rows[sub["id"]] = sub

    assert act_as(STAFF).post(f"/api/v1/subscriptions/{sub['id']}/{action}").status_code == 200


def test_unknown_subscription_is_a_404(act_as, subs):
    assert act_as(OWNER).post(f"/api/v1/subscriptions/{uuid4()}/pause").status_code == 404


def test_customer_cannot_activate(act_as, subs):
    sub = make_subscription(OWNER_ID, status="confirmed")
    subs.rows[sub["id"]] = sub

    assert act_as(OWNER).post(f"/api/v1/subscriptions/{sub['id']}/activate").status_code == 403


@pytest.mark.parametrize("status", ["draft", "quotation", "confirmed"])
def test_customer_cannot_renew_their_way_into_an_active_subscription(act_as, subs, status):
    sub = make_subscription(OWNER_ID, status=status)
    subs.rows[sub["id"]] = sub

    response = act_as(OWNER).post(f"/api/v1/subscriptions/{sub['id']}/renew")

    assert response.status_code == 400
    assert subs.calls.renewals == []


def test_customer_can_renew_an_activated_subscription(act_as, subs):
    sub = make_subscription(OWNER_ID, status="active")
    subs.rows[sub["id"]] = sub

    assert act_as(OWNER).post(f"/api/v1/subscriptions/{sub['id']}/renew").status_code == 200
    assert subs.calls.renewals == [sub["id"]]


def test_staff_can_renew_any_subscription(act_as, subs):
    sub = make_subscription(OTHER_ID, status="draft")
    subs.rows[sub["id"]] = sub

    assert act_as(STAFF).post(f"/api/v1/subscriptions/{sub['id']}/renew").status_code == 200


# --------------------------------------------------------------------------- #
# Creating subscriptions
# --------------------------------------------------------------------------- #

def request_body(customer_id: str) -> dict:
    return {
        "customer_id": customer_id, "plan_id": PLAN_ID, "status": "active", "discount_id": str(uuid4()),
        "lines": [{"product_id": str(uuid4()), "quantity": 1, "unit_price": 0}],
    }


def test_customer_request_is_a_draft_priced_from_the_plan(act_as, subs):
    response = act_as(OWNER).post("/api/v1/subscriptions", json=request_body(OWNER_ID))

    assert response.status_code == 201
    created = subs.calls.created[0]
    assert created.status.value == "draft"
    assert created.lines == []
    assert created.discount_id is None


def test_customer_cannot_create_for_someone_else(act_as, subs):
    response = act_as(OWNER).post("/api/v1/subscriptions", json=request_body(OTHER_ID))

    assert response.status_code == 403
    assert subs.calls.created == []


def test_staff_keep_full_control_when_creating(act_as, subs):
    response = act_as(STAFF).post("/api/v1/subscriptions", json=request_body(OTHER_ID))

    assert response.status_code == 201
    created = subs.calls.created[0]
    assert created.status.value == "active"
    assert len(created.lines) == 1
    assert created.discount_id is not None


# --------------------------------------------------------------------------- #
# Demo data seeder
# --------------------------------------------------------------------------- #

@pytest.fixture()
def seeder(monkeypatch):
    ran = []
    monkeypatch.setattr(billing_service, "seed_demo_data", lambda: ran.append(True) or {"status": "success"})
    return ran


def set_token(monkeypatch, token):
    monkeypatch.setattr(billing_endpoints, "get_settings", lambda: SimpleNamespace(bootstrap_token=token))


def test_seeding_is_disabled_without_a_configured_token(client, monkeypatch, seeder):
    set_token(monkeypatch, None)

    assert client.post("/api/v1/demo/seed", headers={"X-Bootstrap-Token": "anything"}).status_code == 403
    assert seeder == []


@pytest.mark.parametrize("headers", [{}, {"X-Bootstrap-Token": "wrong"}, {"X-Bootstrap-Token": ""}])
def test_seeding_rejects_a_missing_or_wrong_token(client, monkeypatch, seeder, headers):
    set_token(monkeypatch, "s3cret")

    assert client.post("/api/v1/demo/seed", headers=headers).status_code == 403
    assert seeder == []


def test_seeding_runs_with_the_right_token(client, monkeypatch, seeder):
    set_token(monkeypatch, "s3cret")

    response = client.post("/api/v1/demo/seed", headers={"X-Bootstrap-Token": "s3cret"})

    assert response.status_code == 200
    assert seeder == [True]
