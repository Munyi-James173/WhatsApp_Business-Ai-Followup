"""
src/analyser.py
Uses the local LLM to analyse a full conversation thread and decide whether
a follow-up is warranted.  Pure contextual reasoning — no keyword matching.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .config_loader import cfg
from .db import Message
from .llm_client import llm
from .prompts import (
    ANALYSER_SYSTEM, ANALYSER_USER,
    OPT_OUT_SYSTEM, OPT_OUT_USER,
)

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    needs_follow_up: bool
    confidence: float
    stage: str
    reasoning: str
    sentiment: str
    customer_name: Optional[str]
    last_unanswered_topic: Optional[str]


def _format_thread(messages: list[Message]) -> str:
    """Convert message rows into a readable transcript for the LLM."""
    lines = []
    for msg in messages:
        ts = msg.sent_at.strftime("%Y-%m-%d %H:%M")
        who = "Customer" if msg.direction == "inbound" else "Us"
        lines.append(f"[{ts}] {who}: {msg.content}")
    return "\n".join(lines)


async def _opt_out_check(last_customer_message: str) -> bool:
    """
    Secondary LLM-based opt-out detector as a belt-and-suspenders check
    on top of the keyword list in config.
    """
    system = OPT_OUT_SYSTEM
    user   = OPT_OUT_USER.format(message=last_customer_message)
    raw = await llm.chat(system, user)
    return raw.strip().upper().startswith("YES")


def _keyword_opt_out(messages: list[Message]) -> bool:
    """Fast keyword pre-check from config before hitting the LLM."""
    keywords = [k.lower() for k in cfg.opt_out.get("keywords", [])]
    # Only look at the last few inbound messages
    inbound = [m for m in messages if m.direction == "inbound"][-5:]
    for msg in inbound:
        text = msg.content.lower()
        if any(kw in text for kw in keywords):
            return True
    return False


async def analyse(messages: list[Message]) -> AnalysisResult:
    """
    Main entry point.  Takes the full ordered list of messages and returns
    a structured analysis result.
    """
    if not messages:
        return AnalysisResult(
            needs_follow_up=False,
            confidence=1.0,
            stage="already_resolved",
            reasoning="No messages in thread.",
            sentiment="neutral",
            customer_name=None,
            last_unanswered_topic=None,
        )

    # Fast keyword opt-out check (avoids LLM call)
    if _keyword_opt_out(messages):
        logger.info("Keyword opt-out detected — suppressing.")
        return AnalysisResult(
            needs_follow_up=False,
            confidence=1.0,
            stage="opted_out",
            reasoning="Customer used opt-out keyword.",
            sentiment="negative",
            customer_name=None,
            last_unanswered_topic=None,
        )

    thread_text = _format_thread(messages)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    system = ANALYSER_SYSTEM.format(
        business_name=cfg.agent.get("business_name", "Our Company"),
        business_context=cfg.agent.get("business_context", ""),
    )
    user = ANALYSER_USER.format(thread=thread_text, now=now_str)

    try:
        raw = await llm.chat(system, user)
        data = await llm.parse_json_response(raw)
    except Exception as exc:
        logger.error("Analyser LLM call failed: %s", exc)
        # Fail safe: do not follow up if we can't analyse
        return AnalysisResult(
            needs_follow_up=False,
            confidence=0.0,
            stage="default",
            reasoning=f"LLM error: {exc}",
            sentiment="neutral",
            customer_name=None,
            last_unanswered_topic=None,
        )

    needs = bool(data.get("needs_follow_up", False))
    confidence = float(data.get("confidence", 0.0))
    threshold = float(cfg.llm.get("confidence_threshold", 0.72))

    # Apply confidence threshold
    if needs and confidence < threshold:
        logger.info(
            "Follow-up suppressed: confidence %.2f below threshold %.2f",
            confidence, threshold,
        )
        needs = False

    # Secondary LLM opt-out check for negative-sentiment threads
    if needs and data.get("sentiment") == "negative":
        inbound = [m for m in messages if m.direction == "inbound"]
        if inbound:
            opted_out = await _opt_out_check(inbound[-1].content)
            if opted_out:
                logger.info("LLM opt-out check triggered — suppressing.")
                needs = False
                data["stage"] = "opted_out"

    return AnalysisResult(
        needs_follow_up=needs,
        confidence=confidence,
        stage=data.get("stage", "default"),
        reasoning=data.get("reasoning", ""),
        sentiment=data.get("sentiment", "neutral"),
        customer_name=data.get("customer_name"),
        last_unanswered_topic=data.get("last_unanswered_topic"),
    )
