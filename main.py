"""
main.py
Entry point.  Starts the FastAPI webhook server and the APScheduler
background job in a single process.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.config_loader import cfg
from src.db import init_db
from src.executor import execute_due_follow_ups
from src.webhook import app

# ── Logging setup ─────────────────────────────────────────────────────────────
level = getattr(logging, cfg.logging.get("level", "INFO").upper(), logging.INFO)
logging.basicConfig(
    level=level,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/app.log"),
    ],
)
logger = logging.getLogger(__name__)


# ── Scheduler ─────────────────────────────────────────────────────────────────
scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(_app):
    """Run setup on startup and teardown on shutdown."""
    logger.info("Initialising database…")
    await init_db()

    logger.info("Starting follow-up executor (every 60 s)…")
    scheduler.add_job(
        execute_due_follow_ups,
        trigger=IntervalTrigger(seconds=60),
        id="executor",
        replace_existing=True,
    )
    scheduler.start()

    logger.info("WhatsApp AI Follow-Up System is running.")
    yield

    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped.")


# Attach lifespan to the FastAPI app
app.router.lifespan_context = lifespan


if __name__ == "__main__":
    host = cfg.server.get("host", "0.0.0.0")
    port = int(cfg.server.get("port", 8000))
    logger.info("Starting server on %s:%d", host, port)
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,
        log_level="warning",   # uvicorn noise suppressed; we use our own handler
    )
