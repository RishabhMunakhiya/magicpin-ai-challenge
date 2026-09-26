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


def test_healthz_initial():
    response = client.get("/v1/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "uptime_seconds" in data
    assert data["contexts_loaded"] == {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}


def test_metadata():
    response = client.get("/v1/metadata")
    assert response.status_code == 200
    data = response.json()
    assert "team_name" in data
    assert "model" in data
    assert "approach" in data
    assert "version" in data


def test_context_push_and_idempotency():
    # Push category
    payload = {
        "slug": "dentists",
        "voice": {"tone": "peer_clinical", "vocab_taboo": ["guaranteed"]},
        "offer_catalog": [{"id": "den_001", "title": "Dental Cleaning @ ₹299", "value": "299"}],
        "peer_stats": {"avg_rating": 4.4, "avg_ctr": 0.030},
        "digest": [{"id": "d_2026W17_jida_fluoride", "kind": "research", "title": "3-month fluoride recall"}],
    }
    resp1 = client.post("/v1/context", json={
        "scope": "category",
        "context_id": "dentists",
        "version": 1,
        "payload": payload,
        "delivered_at": "2026-04-26T10:00:00Z"
    })
    assert resp1.status_code == 200
    assert resp1.json()["accepted"] is True
    assert resp1.json()["ack_id"] == "ack_dentists_v1"

    # Push same version again (idempotent no-op check)
    resp2 = client.post("/v1/context", json={
        "scope": "category",
        "context_id": "dentists",
        "version": 1,
        "payload": payload,
        "delivered_at": "2026-04-26T10:00:00Z"
    })
    assert resp2.status_code == 200
    assert resp2.json()["accepted"] is True

    # Push version 2 (upgrade)
    resp3 = client.post("/v1/context", json={
        "scope": "category",
        "context_id": "dentists",
        "version": 2,
        "payload": payload,
        "delivered_at": "2026-04-26T10:05:00Z"
    })
    assert resp3.status_code == 200
    assert resp3.json()["accepted"] is True
    assert resp3.json()["ack_id"] == "ack_dentists_v2"

    # Push lower version 1 (conflict check)
    resp4 = client.post("/v1/context", json={
        "scope": "category",
        "context_id": "dentists",
        "version": 1,
        "payload": payload,
        "delivered_at": "2026-04-26T10:06:00Z"
    })
    assert resp4.status_code == 409
    assert resp4.json()["accepted"] is False
    assert resp4.json()["reason"] == "stale_version"
    assert resp4.json()["current_version"] == 2


def test_tick_and_composition():
    # Push Category
    client.post("/v1/context", json={
        "scope": "category",
        "context_id": "dentists",
        "version": 1,
        "payload": {
            "slug": "dentists",
            "voice": {"tone": "peer_clinical"},
            "digest": [{"id": "d_2026W17_jida_fluoride", "title": "3-mo fluoride trial"}],
        },
        "delivered_at": "2026-04-26T10:00:00Z"
    })

    # Push Merchant
    client.post("/v1/context", json={
        "scope": "merchant",
        "context_id": "m_001_drmeera",
        "version": 1,
        "payload": {
            "merchant_id": "m_001_drmeera",
            "category_slug": "dentists",
            "identity": {"name": "Dr. Meera's Dental Clinic", "owner_first_name": "Meera", "locality": "Lajpat Nagar"},
            "customer_aggregate": {"high_risk_adult_count": 124},
            "performance": {"views": 2410, "calls": 18, "ctr": 0.021},
        },
        "delivered_at": "2026-04-26T10:00:00Z"
    })

    # Push Trigger
    client.post("/v1/context", json={
        "scope": "trigger",
        "context_id": "trg_001_research",
        "version": 1,
        "payload": {
            "id": "trg_001_research",
            "scope": "merchant",
            "kind": "research_digest",
            "merchant_id": "m_001_drmeera",
            "customer_id": None,
            "payload": {"category": "dentists", "top_item_id": "d_2026W17_jida_fluoride"},
            "suppression_key": "research:dentists:2026-W17",
            "expires_at": "2026-05-30T00:00:00Z"
        },
        "delivered_at": "2026-04-26T10:00:00Z"
    })

    # Call /v1/tick
    resp = client.post("/v1/tick", json={
        "now": "2026-04-26T10:30:00Z",
        "available_triggers": ["trg_001_research"]
    })
    assert resp.status_code == 200
    actions = resp.json()["actions"]
    assert len(actions) == 1
    action = actions[0]
    assert action["merchant_id"] == "m_001_drmeera"
    assert action["send_as"] == "vera"
    assert "Dr. Meera" in action["body"]
    assert "JIDA" in action["body"]
    assert "http" not in action["body"]

    # Second tick with same trigger should be suppressed
    resp2 = client.post("/v1/tick", json={
        "now": "2026-04-26T10:35:00Z",
        "available_triggers": ["trg_001_research"]
    })
    assert resp2.status_code == 200
    assert len(resp2.json()["actions"]) == 0
