"""
src/scheduler.py
Determines WHEN a follow-up should be sent based on stage and timing rules,
then persists a ScheduledFollowUp record.  Also runs the execution loop that
fires pending follow-ups.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytz
from dateutil import rrule

from .analyser import AnalysisResult
from .config_loader import cfg
from .db import (
    AsyncSessionLocal, ScheduledFollowUp, Thread,
    cancel_pending_for_thread, get_pending_follow_ups,
)

logger = logging.getLogger(__name__)

_DAY_NAMES = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


def _get_timing_rule(stage: str) -> dict:
    rules = cfg.timing.get("rules", {})
    return rules.get(stage, rules.get("default", {"days": 2, "business_hours_only": True}))


def _next_business_datetime(from_dt: datetime) -> datetime:
    """
    Advance from_dt to the next valid business moment according to config.
    """
    bh = cfg.timing.get("business_hours", {})
    tz = pytz.timezone(bh.get("timezone", "UTC"))
    start_h, start_m = map(int, bh.get("start", "09:00").split(":"))
    end_h,   end_m   = map(int, bh.get("end",   "17:30").split(":"))
    working_day_nums  = {_DAY_NAMES[d] for d in bh.get("working_days", ["Mon","Tue","Wed","Thu","Fri"])}

    dt = from_dt.astimezone(tz)

    # Move to the next valid day if needed
    while dt.weekday() not in working_day_nums:
        dt += timedelta(days=1)
        dt = dt.replace(hour=start_h, minute=start_m, second=0, microsecond=0)

    # Move to start of business if before open
    open_time  = dt.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    close_time = dt.replace(hour=end_h,   minute=end_m,   second=0, microsecond=0)

    if dt < open_time:
        dt = open_time
    elif dt >= close_time:
        # Roll to next working day
        dt += timedelta(days=1)
        dt = dt.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        while dt.weekday() not in working_day_nums:
            dt += timedelta(days=1)

    return dt.astimezone(timezone.utc)


def calculate_send_time(stage: str, from_dt: Optional[datetime] = None) -> datetime:
    """
    Return the UTC datetime at which the follow-up should be sent.
    """
    rule = _get_timing_rule(stage)
    base = from_dt or datetime.now(timezone.utc)
    candidate = base + timedelta(days=rule["days"])

    if rule.get("business_hours_only", True):
        candidate = _next_business_datetime(candidate)

    return candidate


async def schedule_follow_up(
    thread: Thread,
    analysis: AnalysisResult,
    drafted_message: Optional[str] = None,
) -> Optional[ScheduledFollowUp]:
    """
    Persist a ScheduledFollowUp row.  Returns None if suppressed by policy.
    """
    # Check thread-level suppression rules
    suppress_after = cfg.opt_out.get("suppress_after_days", 30)
    max_follow_ups = cfg.opt_out.get("max_follow_ups_per_thread", 3)

    if thread.opted_out:
        logger.info("Thread %s opted out — no schedule.", thread.id)
        return None

    if thread.follow_up_count >= max_follow_ups:
        logger.info("Thread %s hit max follow-ups (%d).", thread.id, max_follow_ups)
        return None

    if thread.last_message_at:
        age_days = (datetime.now(timezone.utc) - thread.last_message_at).days
        if age_days > suppress_after:
            logger.info("Thread %s is %d days old — suppressed.", thread.id, age_days)
            return None

    send_at = calculate_send_time(analysis.stage, thread.last_message_at)

    async with AsyncSessionLocal() as session:
        # Cancel any existing pending follow-up for this thread
        await cancel_pending_for_thread(session, thread.id)

        record = ScheduledFollowUp(
            thread_id=thread.id,
            scheduled_for=send_at,
            stage=analysis.stage,
            confidence=analysis.confidence,
            reasoning=analysis.reasoning,
            drafted_message=drafted_message,
            status="pending",
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)

    logger.info(
        "Scheduled follow-up for thread %s at %s (stage=%s, confidence=%.2f)",
        thread.id, send_at.isoformat(), analysis.stage, analysis.confidence,
    )
    return record


async def get_due_follow_ups() -> list[ScheduledFollowUp]:
    """Return all pending follow-ups whose scheduled time has arrived."""
    async with AsyncSessionLocal() as session:
        return await get_pending_follow_ups(session)
