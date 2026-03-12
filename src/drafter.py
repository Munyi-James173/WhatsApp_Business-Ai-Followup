"""
src/drafter.py
Generates the actual follow-up message text using the local LLM.
"""
from __future__ import annotations

import logging

from .analyser import AnalysisResult
from .config_loader import cfg
from .llm_client import llm
from .prompts import DRAFTER_SYSTEM, DRAFTER_USER

logger = logging.getLogger(__name__)


async def draft_message(analysis: AnalysisResult) -> str:
    """
    Use the local LLM to write a natural, context-aware follow-up message.
    Returns the message text ready to send.
    """
    agent_name    = cfg.agent.get("agent_name", "Alex")
    business_name = cfg.agent.get("business_name", "Our Company")
    customer_name = analysis.customer_name or "there"

    system = DRAFTER_SYSTEM.format(
        agent_name=agent_name,
        business_name=business_name,
    )
    user = DRAFTER_USER.format(
        customer_name=customer_name,
        last_unanswered_topic=analysis.last_unanswered_topic or "your inquiry",
        stage=analysis.stage,
        sentiment=analysis.sentiment,
    )

    try:
        message = await llm.chat(system, user)
    except Exception as exc:
        logger.error("Drafter LLM call failed: %s", exc)
        # Graceful fallback — generic but still friendly
        message = (
            f"Hi {customer_name}, just wanted to check in and see if you had "
            f"any questions. Happy to help whenever you're ready. — {agent_name}"
        )

    # Trim whitespace and any stray quotes the model might add
    message = message.strip().strip('"').strip("'")

    logger.info("Drafted message (%d chars): %s", len(message), message[:80])
    return message
