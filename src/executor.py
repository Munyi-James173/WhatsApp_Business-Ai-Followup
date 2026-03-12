"""
src/executor.py
Polls for due follow-ups and fires them.  Runs as a background task inside
the main process (APScheduler).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from .db import AsyncSessionLocal, ScheduledFollowUp, get_thread_messages, upsert_thread
from .drafter import draft_message
from .analyser import analyse
from .logger import log_error, log_sent, log_suppressed
from .scheduler import get_due_follow_ups
from .sender import send_whatsapp_message

logger = logging.getLogger(__name__)


async def execute_due_follow_ups() -> None:
    """
    Called by APScheduler every minute.
    Finds pending follow-ups whose time has arrived and sends them.
    """
    due = await get_due_follow_ups()
    if not due:
        return

    logger.info("Executing %d due follow-up(s).", len(due))

    for record in due:
        try:
            await _execute_one(record)
        except Exception as exc:
            logger.error("Error executing follow-up %d: %s", record.id, exc)
            log_error(record.thread_id, str(exc))
            async with AsyncSessionLocal() as session:
                r = await session.get(ScheduledFollowUp, record.id)
                if r:
                    r.status = "error"
                    await session.commit()


async def _execute_one(record: ScheduledFollowUp) -> None:
    """Send a single follow-up message."""
    async with AsyncSessionLocal() as session:
        thread = await upsert_thread(session, record.thread_id)

    # Final suppression checks
    if thread.opted_out:
        log_suppressed(record.thread_id, "opted_out at execution time")
        await _mark(record.id, "suppressed")
        return

    # Use stored draft or re-draft if missing
    message_text = record.drafted_message
    if not message_text:
        async with AsyncSessionLocal() as session:
            messages = await get_thread_messages(session, record.thread_id)
        analysis = await analyse(messages)
        message_text = await draft_message(analysis)

    # Send
    result = await send_whatsapp_message(thread.customer_phone, message_text)

    if result.success:
        log_sent(
            thread_id=record.thread_id,
            message=message_text,
            provider_message_id=result.provider_message_id,
            stage=record.stage or "unknown",
        )
        # Store our outbound message and update thread
        from .db import add_message
        async with AsyncSessionLocal() as session:
            await add_message(
                session, record.thread_id, "outbound", message_text,
                wa_msg_id=result.provider_message_id,
                sent_at=datetime.now(timezone.utc),
            )
            await upsert_thread(
                session, record.thread_id,
                last_our_msg_at=datetime.now(timezone.utc),
                follow_up_count=thread.follow_up_count + 1,
            )
        await _mark(record.id, "sent")
    else:
        log_error(record.thread_id, f"Send failed: {result.error}")
        await _mark(record.id, "error")


async def _mark(record_id: int, status: str) -> None:
    async with AsyncSessionLocal() as session:
        r = await session.get(ScheduledFollowUp, record_id)
        if r:
            r.status = status
            r.executed_at = datetime.now(timezone.utc)
            await session.commit()
