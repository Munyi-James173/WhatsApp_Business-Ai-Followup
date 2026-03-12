"""
src/db.py
SQLite-backed conversation store using SQLAlchemy (async).
Run `python -m src.db init` to create the schema.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer, String, Text, create_engine,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


DB_PATH = Path("data/followup.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

ASYNC_URL = f"sqlite+aiosqlite:///{DB_PATH}"
SYNC_URL  = f"sqlite:///{DB_PATH}"


# ── ORM Models ───────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class Thread(Base):
    __tablename__ = "threads"

    id               = Column(String, primary_key=True)   # phone number or thread ID
    customer_phone   = Column(String, nullable=False)
    customer_name    = Column(String, nullable=True)
    last_message_at  = Column(DateTime(timezone=True), nullable=True)
    last_our_msg_at  = Column(DateTime(timezone=True), nullable=True)
    opted_out        = Column(Boolean, default=False)
    follow_up_count  = Column(Integer, default=0)
    stage            = Column(String, nullable=True)
    sentiment        = Column(String, nullable=True)
    created_at       = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at       = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                              onupdate=lambda: datetime.now(timezone.utc))


class Message(Base):
    __tablename__ = "messages"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    thread_id   = Column(String, nullable=False, index=True)
    direction   = Column(String, nullable=False)   # inbound | outbound
    content     = Column(Text, nullable=False)
    wa_msg_id   = Column(String, nullable=True)    # WhatsApp message ID
    sent_at     = Column(DateTime(timezone=True), nullable=False)


class ScheduledFollowUp(Base):
    __tablename__ = "scheduled_follow_ups"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    thread_id       = Column(String, nullable=False, index=True)
    scheduled_for   = Column(DateTime(timezone=True), nullable=False)
    stage           = Column(String, nullable=True)
    confidence      = Column(Float, nullable=True)
    reasoning       = Column(Text, nullable=True)
    drafted_message = Column(Text, nullable=True)
    status          = Column(String, default="pending")  # pending | sent | cancelled | suppressed
    created_at      = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    executed_at     = Column(DateTime(timezone=True), nullable=True)


# ── Engine / Session factory ──────────────────────────────────────────────────

_async_engine = create_async_engine(ASYNC_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(_async_engine, expire_on_commit=False)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    async with _async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ── CRUD helpers ─────────────────────────────────────────────────────────────

async def upsert_thread(session: AsyncSession, phone: str, **kwargs) -> Thread:
    result = await session.get(Thread, phone)
    if result is None:
        result = Thread(id=phone, customer_phone=phone, **kwargs)
        session.add(result)
    else:
        for k, v in kwargs.items():
            setattr(result, k, v)
        result.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(result)
    return result


async def add_message(
    session: AsyncSession,
    thread_id: str,
    direction: str,
    content: str,
    wa_msg_id: Optional[str] = None,
    sent_at: Optional[datetime] = None,
) -> Message:
    msg = Message(
        thread_id=thread_id,
        direction=direction,
        content=content,
        wa_msg_id=wa_msg_id,
        sent_at=sent_at or datetime.now(timezone.utc),
    )
    session.add(msg)
    await session.commit()
    return msg


async def get_thread_messages(session: AsyncSession, thread_id: str) -> list[Message]:
    result = await session.execute(
        select(Message)
        .where(Message.thread_id == thread_id)
        .order_by(Message.sent_at)
    )
    return list(result.scalars().all())


async def get_pending_follow_ups(session: AsyncSession) -> list[ScheduledFollowUp]:
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(ScheduledFollowUp)
        .where(
            ScheduledFollowUp.status == "pending",
            ScheduledFollowUp.scheduled_for <= now,
        )
    )
    return list(result.scalars().all())


async def cancel_pending_for_thread(session: AsyncSession, thread_id: str) -> None:
    result = await session.execute(
        select(ScheduledFollowUp).where(
            ScheduledFollowUp.thread_id == thread_id,
            ScheduledFollowUp.status == "pending",
        )
    )
    for row in result.scalars().all():
        row.status = "cancelled"
    await session.commit()


# ── CLI: python -m src.db init ───────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio

    async def _main():
        await init_db()
        print("Database initialised at", DB_PATH)

    if len(sys.argv) > 1 and sys.argv[1] == "init":
        asyncio.run(_main())
    else:
        print("Usage: python -m src.db init")
