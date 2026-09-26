from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from models import (
    ContextCounts,
    ContextRequest,
    HealthzResponse,
    MetadataResponse,
    ReplyRequest,
    ReplyResponse,
    TickAction,
    TickRequest,
    TickResponse,
)
from state import store
from validators import sanitize_urls, validate_action_fields, validate_no_urls
from vera_engine import engine

# Setup logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("vera-bot")

app = FastAPI(
    title="Magicpin Vera AI Bot",
    description="Production-grade AI Assistant for WhatsApp Merchant & Customer Engagement",
    version="1.0.0",
)

# Enable CORS for judge / browser calls
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------------
# 1. GET /v1/healthz — Liveness Probe
# -----------------------------------------------------------------------------
@app.get("/v1/healthz", response_model=HealthzResponse, tags=["Health"])
async def healthz():
    counts_dict = store.get_context_counts()
    counts = ContextCounts(
        category=counts_dict.get("category", 0),
        merchant=counts_dict.get("merchant", 0),
        customer=counts_dict.get("customer", 0),
        trigger=counts_dict.get("trigger", 0),
    )
    return HealthzResponse(
        status="ok",
        uptime_seconds=store.get_uptime_seconds(),
        contexts_loaded=counts,
    )


# -----------------------------------------------------------------------------
# 2. GET /v1/metadata — Bot Identity
# -----------------------------------------------------------------------------
@app.get("/v1/metadata", response_model=MetadataResponse, tags=["Metadata"])
async def metadata():
    return MetadataResponse(
        team_name="Team Vera AI",
        team_members=["Senior AI Backend Engineer"],
        model="deterministic-4-context-expert",
        approach="Deterministic 4-context semantic composer with rule-based trigger routing, category voice adaptation, multi-turn state machine, and auto-reply detection",
        contact_email="team@example.com",
        version="1.0.0",
        submitted_at="2026-04-26T08:00:00Z",
    )


# -----------------------------------------------------------------------------
# 3. POST /v1/context — Ingest Context
# -----------------------------------------------------------------------------
@app.post("/v1/context", tags=["Context"])
async def push_context(body: ContextRequest):
    accepted, ack_or_reason, cur_ver = store.store_context(
        scope=body.scope,
        context_id=body.context_id,
        version=body.version,
        payload=body.payload,
        delivered_at=body.delivered_at,
    )

    if not accepted:
        # Version conflict (already have equal or higher version)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "accepted": False,
                "reason": ack_or_reason,
                "current_version": cur_ver if cur_ver is not None else body.version,
            },
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "accepted": True,
            "ack_id": ack_or_reason,
            "stored_at": datetime.now(timezone.utc).isoformat(),
        },
    )


# -----------------------------------------------------------------------------
# 4. POST /v1/tick — Proactive Send Decisions
# -----------------------------------------------------------------------------
@app.post("/v1/tick", response_model=TickResponse, tags=["Tick"])
async def tick(body: TickRequest):
    actions: List[TickAction] = []
    
    # Track merchants messaged in this tick to avoid duplicate actions in one tick
    messaged_merchants_in_tick = set()

    for trg_id in body.available_triggers:
        if len(actions) >= 20:
            break

        trigger = store.get_context("trigger", trg_id)
        if not trigger:
            continue

        # Check expiration
        expires_at = trigger.get("expires_at")
        if expires_at and body.now:
            try:
                # Compare ISO strings safely
                if body.now > expires_at:
                    continue
            except Exception:
                pass

        supp_key = trigger.get("suppression_key", "")
        merchant_id = trigger.get("merchant_id", "")
        customer_id = trigger.get("customer_id")

        if merchant_id in messaged_merchants_in_tick:
            continue

        if store.is_suppressed(supp_key, merchant_id):
            continue

        merchant = store.get_context("merchant", merchant_id)
        if not merchant:
            continue

        cat_slug = merchant.get("category_slug")
        category = store.get_context("category", cat_slug)
        if not category:
            continue

        customer = store.get_context("customer", customer_id) if customer_id else None

        # Compose message
        composed = engine.compose(
            category=category,
            merchant=merchant,
            trigger=trigger,
            customer=customer,
        )

        # Sanitize any accidental URLs
        clean_body = sanitize_urls(composed.body)

        action_dict = {
            "conversation_id": composed.conversation_id,
            "merchant_id": composed.merchant_id,
            "customer_id": composed.customer_id,
            "send_as": composed.send_as,
            "trigger_id": composed.trigger_id,
            "template_name": composed.template_name,
            "template_params": composed.template_params,
            "body": clean_body,
            "cta": composed.cta,
            "suppression_key": composed.suppression_key,
            "rationale": composed.rationale,
        }

        # Validate action fields
        errs = validate_action_fields(action_dict)
        if errs:
            logger.warning(f"Validation error in action for trigger {trg_id}: {errs}")
            continue

        # Record action in state store
        store.record_action(action_dict)
        messaged_merchants_in_tick.add(merchant_id)

        actions.append(TickAction(**action_dict))

    return TickResponse(actions=actions)


# -----------------------------------------------------------------------------
# 5. POST /v1/reply — Multi-Turn Inbound Response
# -----------------------------------------------------------------------------
@app.post("/v1/reply", response_model=ReplyResponse, tags=["Reply"])
async def reply(body: ReplyRequest):
    # Record inbound turn and get conversation state
    conv_state = store.record_inbound_reply(
        conv_id=body.conversation_id,
        merchant_id=body.merchant_id,
        customer_id=body.customer_id,
        from_role=body.from_role,
        message=body.message,
        turn_number=body.turn_number,
    )

    merchant = store.get_context("merchant", body.merchant_id or conv_state.get("merchant_id"))
    category = store.get_context("category", merchant.get("category_slug")) if merchant else None

    # Process reply through engine
    reply_resp = engine.handle_reply(
        conversation_id=body.conversation_id,
        message=body.message,
        turn_number=body.turn_number,
        merchant_id=body.merchant_id,
        customer_id=body.customer_id,
        from_role=body.from_role,
        conv_state=conv_state,
        category=category,
        merchant=merchant,
    )

    # Sanitize body if present
    clean_body = sanitize_urls(reply_resp.body) if reply_resp.body else None

    # Record outbound reply in state
    store.record_outbound_reply(
        conv_id=body.conversation_id,
        action=reply_resp.action,
        body=clean_body,
        rationale=reply_resp.rationale,
        cta=reply_resp.cta,
    )

    return ReplyResponse(
        action=reply_resp.action,
        body=clean_body,
        wait_seconds=reply_resp.wait_seconds,
        cta=reply_resp.cta,
        rationale=reply_resp.rationale,
    )


# -----------------------------------------------------------------------------
# Teardown / Reset Endpoint
# -----------------------------------------------------------------------------
@app.post("/v1/teardown", tags=["Lifecycle"])
async def teardown():
    store.wipe_state()
    return {"status": "ok", "message": "State store wiped successfully"}
