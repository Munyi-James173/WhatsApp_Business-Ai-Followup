"""
src/logger.py
Structured audit trail.  Every follow-up decision and send attempt is
written as a JSON line to logs/audit.jsonl.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config_loader import cfg

_log_path = Path(cfg.logging.get("audit_file", "logs/audit.jsonl"))
_log_path.parent.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)


def _write(event: dict[str, Any]) -> None:
    event.setdefault("ts", datetime.now(timezone.utc).isoformat())
    try:
        with open(_log_path, "a") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.error("Audit log write failed: %s", exc)


def log_analysis(
    thread_id: str,
    needs_follow_up: bool,
    confidence: float,
    stage: str,
    reasoning: str,
    sentiment: str,
) -> None:
    _write({
        "action": "analysis_complete",
        "thread_id": thread_id,
        "needs_follow_up": needs_follow_up,
        "confidence": confidence,
        "stage": stage,
        "reasoning": reasoning,
        "sentiment": sentiment,
    })


def log_scheduled(
    thread_id: str,
    scheduled_for: datetime,
    stage: str,
    confidence: float,
) -> None:
    _write({
        "action": "follow_up_scheduled",
        "thread_id": thread_id,
        "scheduled_for": scheduled_for.isoformat(),
        "stage": stage,
        "confidence": confidence,
    })


def log_sent(
    thread_id: str,
    message: str,
    provider_message_id: Optional[str],
    stage: str,
) -> None:
    _write({
        "action": "follow_up_sent",
        "thread_id": thread_id,
        "message": message,
        "provider_message_id": provider_message_id,
        "stage": stage,
    })


def log_suppressed(thread_id: str, reason: str) -> None:
    _write({
        "action": "follow_up_suppressed",
        "thread_id": thread_id,
        "reason": reason,
    })


def log_error(thread_id: str, error: str) -> None:
    _write({
        "action": "error",
        "thread_id": thread_id,
        "error": error,
    })


def log_inbound(thread_id: str, message: str) -> None:
    _write({
        "action": "inbound_message",
        "thread_id": thread_id,
        "preview": message[:120],
    })
