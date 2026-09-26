from __future__ import annotations

from typing import Any, Dict, Optional
from main import app
from models import ComposedMessage
from vera_engine import engine


def compose(
    category: Dict[str, Any],
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    customer: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Submission entrypoint per §7.1 of challenge-brief.md.
    Inputs are dicts loaded from the dataset JSON.
    Returns a dict with keys: body, cta, send_as, suppression_key, rationale.
    """
    msg: ComposedMessage = engine.compose(
        category=category,
        merchant=merchant,
        trigger=trigger,
        customer=customer,
    )
    return {
        "conversation_id": msg.conversation_id,
        "merchant_id": msg.merchant_id,
        "customer_id": msg.customer_id,
        "send_as": msg.send_as,
        "trigger_id": msg.trigger_id,
        "template_name": msg.template_name,
        "template_params": msg.template_params,
        "body": msg.body,
        "cta": msg.cta,
        "suppression_key": msg.suppression_key,
        "rationale": msg.rationale,
    }


def respond(state: Dict[str, Any], merchant_message: str) -> Dict[str, Any]:
    """
    Multi-turn handler per §7.4 of challenge-brief.md.
    """
    conv_id = state.get("conversation_id", "conv_default")
    turn_num = len(state.get("turns", [])) + 1
    mid = state.get("merchant_id")
    cid = state.get("customer_id")
    resp = engine.handle_reply(
        conversation_id=conv_id,
        message=merchant_message,
        turn_number=turn_num,
        merchant_id=mid,
        customer_id=cid,
        from_role="merchant",
        conv_state=state,
    )
    return {
        "action": resp.action,
        "body": resp.body,
        "wait_seconds": resp.wait_seconds,
        "cta": resp.cta,
        "rationale": resp.rationale,
    }
