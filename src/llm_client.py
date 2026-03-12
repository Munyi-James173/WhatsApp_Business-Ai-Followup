"""
src/llm_client.py
Thin async wrapper around Ollama (primary) and llama.cpp server (fallback).
All inference stays on-prem; no external API calls after initial model pull.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .config_loader import cfg

logger = logging.getLogger(__name__)


class LLMClient:
    """Unified interface for local LLM inference."""

    def __init__(self):
        self.provider = cfg.llm.get("provider", "ollama")
        self.model = cfg.llm.get("model", "mistral:7b-instruct")
        self.temperature = float(cfg.llm.get("temperature", 0.7))
        self.max_tokens = int(cfg.llm.get("max_tokens", 512))

        if self.provider == "ollama":
            self.base_url = cfg.llm.get("base_url", "http://localhost:11434")
        else:
            self.base_url = cfg.llm.get("llamacpp_server_url", "http://localhost:8080")

    async def chat(self, system: str, user: str) -> str:
        """
        Send a system + user message pair and return the assistant reply as a string.
        Retries once on transient errors.
        """
        for attempt in range(2):
            try:
                if self.provider == "ollama":
                    return await self._ollama_chat(system, user)
                else:
                    return await self._llamacpp_chat(system, user)
            except Exception as exc:
                if attempt == 0:
                    logger.warning("LLM call failed (attempt 1): %s — retrying", exc)
                else:
                    raise

    # ── Ollama ────────────────────────────────────────────────────────────────

    async def _ollama_chat(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"].strip()

    # ── llama.cpp server ──────────────────────────────────────────────────────

    async def _llamacpp_chat(self, system: str, user: str) -> str:
        # llama.cpp's OpenAI-compatible /v1/chat/completions endpoint
        payload = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()

    async def parse_json_response(self, raw: str) -> dict[str, Any]:
        """
        Safely parse JSON from LLM output.
        Strips markdown fences if the model wrapped the response.
        """
        text = raw.strip()
        # Strip ```json ... ``` fences
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Attempt to extract first {...} block
            start = text.find("{")
            end   = text.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(text[start:end])
            raise ValueError(f"LLM returned non-JSON output: {raw[:200]}")


# Singleton
llm = LLMClient()
