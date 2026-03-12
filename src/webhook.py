"""
src/webhook.py
FastAPI application that receives WhatsApp messages from Meta Cloud API
or Twilio, stores them, and triggers analysis + scheduling.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response

from .analyser import analyse
from .config_loader import cfg
from .db import AsyncSessionLocal, add_message, cancel_pending_for_thread, get_thread_messages, upsert_thread
from .drafter import draft_message
from .logger import log_analysis, log_inbound, log_scheduled, log_suppressed
from .scheduler import schedule_follow_up

logger = logging.getLogger(__name__)

app = FastAPI(title="WhatsApp AI Follow-Up")


# ── Webhook verification (Meta GET request) ───────────────────────────────────

@app.get("/webhook")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    mode      = params.get("hub.mode")
    token     = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == cfg.whatsapp.get("verify_token", ""):
        logger.info("Webhook verified successfully.")
        return Response(content=challenge, media_type="text/plain")

    raise HTTPException(status_code=403, detail="Verification failed")


# ── Incoming message handler ──────────────────────────────────────────────────

@app.post("/webhook")
async def receive_message(request: Request):
    """
    Accepts incoming WhatsApp messages from either Meta Cloud API or Twilio.
    Parses the payload, stores the message, and kicks off analysis.
    """
    body = await request.body()
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        payload = json.loads(body)
        await _handle_cloud_api(payload)
    elif "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        await _handle_twilio(dict(form))
    else:
        logger.warning("Unknown content type: %s", content_type)

    # Always return 200 to acknowledge receipt
    return {"status": "ok"}


async def _handle_cloud_api(payload: dict[str, Any]) -> None:
    """Parse Meta Cloud API webhook payload."""
    try:
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return  # Status update, not a message

        msg = messages[0]
        from_phone = msg.get("from", "")
        msg_type   = msg.get("type", "")
        wa_msg_id  = msg.get("id", "")
        ts         = datetime.fromtimestamp(
            int(msg.get("timestamp", 0)), tz=timezone.utc
        )

        if msg_type == "text":
            text = msg["text"]["body"]
        elif msg_type in ("image", "document", "audio", "video"):
            text = f"[{msg_type.upper()} received]"
        else:
            return  # Ignore other types

        await _process_inbound(from_phone, text, wa_msg_id, ts)

    except Exception as exc:
        logger.error("Error parsing Cloud API payload: %s", exc)


async def _handle_twilio(form: dict[str, str]) -> None:
    """Parse Twilio WhatsApp webhook form data."""
    try:
        from_raw = form.get("From", "")
        from_phone = from_raw.replace("whatsapp:", "")
        text = form.get("Body", "")
        wa_msg_id = form.get("MessageSid", "")
        ts = datetime.now(timezone.utc)

        if not text:
            return

        await _process_inbound(from_phone, text, wa_msg_id, ts)

    except Exception as exc:
        logger.error("Error parsing Twilio payload: %s", exc)


async def _process_inbound(
    phone: str,
    text: str,
    wa_msg_id: str,
    ts: datetime,
) -> None:
    """
    Core pipeline:
    1. Store the inbound message
    2. Cancel any pending follow-up (customer replied — no need)
    3. Update thread metadata
    4. Run the analyser
    5. Schedule a follow-up if warranted
    """
    log_inbound(phone, text)
    logger.info("Inbound from %s: %s", phone, text[:60])

    async with AsyncSessionLocal() as session:
        # Store message
        await add_message(session, phone, "inbound", text, wa_msg_id, ts)

        # Customer replied — cancel any waiting follow-up
        await cancel_pending_for_thread(session, phone)

        # Update thread record
        thread = await upsert_thread(
            session, phone,
            last_message_at=ts,
        )

    # Re-fetch full thread for analysis
    async with AsyncSessionLocal() as session:
        messages = await get_thread_messages(session, phone)
        thread = await upsert_thread(session, phone)  # get current state

    # Run analyser (LLM call)
    analysis = await analyse(messages)

    log_analysis(
        thread_id=phone,
        needs_follow_up=analysis.needs_follow_up,
        confidence=analysis.confidence,
        stage=analysis.stage,
        reasoning=analysis.reasoning,
        sentiment=analysis.sentiment,
    )

    if analysis.customer_name:
        async with AsyncSessionLocal() as session:
            await upsert_thread(session, phone, customer_name=analysis.customer_name)

    if analysis.stage == "opted_out":
        async with AsyncSessionLocal() as session:
            await upsert_thread(session, phone, opted_out=True)
        log_suppressed(phone, "opted_out")
        return

    if not analysis.needs_follow_up:
        log_suppressed(phone, f"analyser decision (stage={analysis.stage}, confidence={analysis.confidence:.2f})")
        return

    # Draft the message now (stored in DB; re-drafted at send time if stale)
    drafted = await draft_message(analysis)

    # Schedule
    async with AsyncSessionLocal() as session:
        thread = await upsert_thread(
            session, phone,
            stage=analysis.stage,
            sentiment=analysis.sentiment,
        )

    record = await schedule_follow_up(thread, analysis, drafted_message=drafted)
    if record:
        log_scheduled(phone, record.scheduled_for, analysis.stage, analysis.confidence)
