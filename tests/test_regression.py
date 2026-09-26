from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from main import app
from state import store

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_state():
    store.wipe_state()
    yield
    store.wipe_state()


def test_cross_merchant_isolation():
    # Push Merchant A
    client.post("/v1/context", json={
        "scope": "merchant",
        "context_id": "m_AAA",
        "version": 1,
        "payload": {
            "merchant_id": "m_AAA",
            "category_slug": "dentists",
            "identity": {"name": "Clinic A", "owner_first_name": "Alice"},
            "performance": {"views": 1000},
        },
        "delivered_at": "2026-04-26T10:00:00Z",
    })

    # Push Merchant B
    client.post("/v1/context", json={
        "scope": "merchant",
        "context_id": "m_BBB",
        "version": 1,
        "payload": {
            "merchant_id": "m_BBB",
            "category_slug": "salons",
            "identity": {"name": "Salon B", "owner_first_name": "Bob"},
            "performance": {"views": 5000},
        },
        "delivered_at": "2026-04-26T10:00:00Z",
    })

    mA = store.get_context("merchant", "m_AAA")
    mB = store.get_context("merchant", "m_BBB")

    assert mA["identity"]["owner_first_name"] == "Alice"
    assert mB["identity"]["owner_first_name"] == "Bob"
    assert mA["category_slug"] == "dentists"
    assert mB["category_slug"] == "salons"


def test_malformed_scope_handling():
    resp = client.post("/v1/context", json={
        "scope": "invalid_scope",
        "context_id": "foo",
        "version": 1,
        "payload": {},
        "delivered_at": "2026-04-26T10:00:00Z",
    })
    assert resp.status_code == 422  # Pydantic validation error


def test_tick_with_unknown_triggers():
    resp = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": ["non_existent_trigger_1", "non_existent_trigger_2"]
    })
    assert resp.status_code == 200
    assert resp.json()["actions"] == []


def test_expired_trigger_ignored():
    # Push Category & Merchant
    client.post("/v1/context", json={
        "scope": "category",
        "context_id": "dentists",
        "version": 1,
        "payload": {"slug": "dentists"},
        "delivered_at": "2026-04-26T10:00:00Z",
    })
    client.post("/v1/context", json={
        "scope": "merchant",
        "context_id": "m_001",
        "version": 1,
        "payload": {"merchant_id": "m_001", "category_slug": "dentists", "identity": {"name": "Test Clinic"}},
        "delivered_at": "2026-04-26T10:00:00Z",
    })

    # Expired trigger
    client.post("/v1/context", json={
        "scope": "trigger",
        "context_id": "trg_expired",
        "version": 1,
        "payload": {
            "id": "trg_expired",
            "scope": "merchant",
            "kind": "curious_ask_due",
            "merchant_id": "m_001",
            "suppression_key": "supp_expired",
            "expires_at": "2026-01-01T00:00:00Z",
        },
        "delivered_at": "2026-04-26T10:00:00Z",
    })

    resp = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": ["trg_expired"]
    })
    assert resp.status_code == 200
    assert len(resp.json()["actions"]) == 0


def test_festival_upcoming_grounded_specificity():
    client.post("/v1/context", json={
        "scope": "category",
        "context_id": "salons",
        "version": 1,
        "payload": {"slug": "salons"},
        "delivered_at": "2026-04-26T10:00:00Z",
    })
    client.post("/v1/context", json={
        "scope": "merchant",
        "context_id": "m_003",
        "version": 1,
        "payload": {
            "merchant_id": "m_003",
            "category_slug": "salons",
            "identity": {"name": "Studio 11", "owner_first_name": "Lakshmi"},
        },
        "delivered_at": "2026-04-26T10:00:00Z",
    })
    client.post("/v1/context", json={
        "scope": "trigger",
        "context_id": "trg_006",
        "version": 1,
        "payload": {
            "id": "trg_006",
            "scope": "merchant",
            "kind": "festival_upcoming",
            "merchant_id": "m_003",
            "payload": {"festival": "Diwali", "date": "2026-10-31", "days_until": 188},
            "urgency": 1,
            "suppression_key": "festival:diwali:2026:m_003",
            "expires_at": "2026-11-02T00:00:00Z",
        },
        "delivered_at": "2026-04-26T10:00:00Z",
    })

    resp = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": ["trg_006"]
    })
    assert resp.status_code == 200
    actions = resp.json()["actions"]
    assert len(actions) == 1
    body = actions[0]["body"]
    assert "Diwali" in body
    assert "188 days" in body
    assert "2026-10-31" in body or "35%" in body
    assert "http" not in body.lower()
    assert actions[0]["send_as"] == "vera"


def test_lifecycle_renewal_and_winback_grounded_specificity():
    client.post("/v1/context", json={
        "scope": "category",
        "context_id": "dentists",
        "version": 1,
        "payload": {"slug": "dentists"},
        "delivered_at": "2026-04-26T10:00:00Z",
    })
    client.post("/v1/context", json={
        "scope": "merchant",
        "context_id": "m_002",
        "version": 1,
        "payload": {
            "merchant_id": "m_002",
            "category_slug": "dentists",
            "identity": {"name": "Bharat Dental", "owner_first_name": "Bharat"},
        },
        "delivered_at": "2026-04-26T10:00:00Z",
    })
    client.post("/v1/context", json={
        "scope": "trigger",
        "context_id": "trg_005",
        "version": 1,
        "payload": {
            "id": "trg_005",
            "scope": "merchant",
            "kind": "renewal_due",
            "merchant_id": "m_002",
            "payload": {"days_remaining": 12, "plan": "Pro", "renewal_amount": 4999},
            "urgency": 4,
            "suppression_key": "renewal:m_002:2026-Q2",
            "expires_at": "2026-05-08T00:00:00Z",
        },
        "delivered_at": "2026-04-26T10:00:00Z",
    })

    resp = client.post("/v1/tick", json={
        "now": "2026-04-26T10:00:00Z",
        "available_triggers": ["trg_005"]
    })
    assert resp.status_code == 200
    actions = resp.json()["actions"]
    assert len(actions) == 1
    body = actions[0]["body"]
    assert "12 days" in body
    assert "4999" in body or "Pro" in body

