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


def test_auto_reply_hell():
    # Simulate turn 1 auto-reply
    auto_msg = "Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly."
    resp1 = client.post("/v1/reply", json={
        "conversation_id": "conv_auto_test",
        "merchant_id": "m_001",
        "customer_id": None,
        "from_role": "merchant",
        "message": auto_msg,
        "received_at": "2026-04-26T10:00:00Z",
        "turn_number": 2,
    })
    assert resp1.status_code == 200
    action1 = resp1.json()["action"]
    assert action1 in ("end", "wait")

    # Simulate turn 2 repeated auto-reply
    resp2 = client.post("/v1/reply", json={
        "conversation_id": "conv_auto_test",
        "merchant_id": "m_001",
        "customer_id": None,
        "from_role": "merchant",
        "message": auto_msg,
        "received_at": "2026-04-26T10:05:00Z",
        "turn_number": 3,
    })
    assert resp2.status_code == 200
    assert resp2.json()["action"] in ("end", "wait")


def test_intent_transition():
    # Set up conversation state with initial proposal
    store.record_action({
        "conversation_id": "conv_intent_test",
        "merchant_id": "m_001",
        "body": "JIDA issue landed. Want me to draft the patient WhatsApp post?",
        "send_as": "vera",
        "trigger_id": "trg_001",
        "template_name": "t1",
        "template_params": [],
        "cta": "open_ended",
        "suppression_key": "k1",
        "rationale": "r1",
    })

    # Merchant says: "Ok lets do it. Whats next?"
    resp = client.post("/v1/reply", json={
        "conversation_id": "conv_intent_test",
        "merchant_id": "m_001",
        "customer_id": None,
        "from_role": "merchant",
        "message": "Ok lets do it. Whats next?",
        "received_at": "2026-04-26T10:10:00Z",
        "turn_number": 2,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "send"
    body = data["body"].lower()
    
    # Must contain actioning words
    actioning = ["done", "sending", "draft", "here", "confirm", "proceed", "next"]
    assert any(w in body for w in actioning)
    
    # Must NOT contain qualifying words
    qualifying = ["would you", "do you", "can you tell", "what if", "how about"]
    assert not any(w in body for w in qualifying)


def test_hostile_handling():
    resp = client.post("/v1/reply", json={
        "conversation_id": "conv_hostile_test",
        "merchant_id": "m_001",
        "customer_id": None,
        "from_role": "merchant",
        "message": "Stop messaging me. This is useless spam.",
        "received_at": "2026-04-26T10:15:00Z",
        "turn_number": 2,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] in ("end", "send")
    if data["action"] == "send":
        assert any(w in data["body"].lower() for w in ["sorry", "apolog", "won't", "wont"])


def test_off_topic_curveball():
    resp = client.post("/v1/reply", json={
        "conversation_id": "conv_curveball_test",
        "merchant_id": "m_001",
        "customer_id": None,
        "from_role": "merchant",
        "message": "Btw can you also help me with my GST filing this month?",
        "received_at": "2026-04-26T10:20:00Z",
        "turn_number": 2,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "send"
    body = data["body"].lower()
    assert "ca" in body or "outside" in body or "gst" in body
