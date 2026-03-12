"""
src/sender.py
Dispatches messages through Meta WhatsApp Cloud API or Twilio.
Supports both providers; configured via settings.yaml.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from .config_loader import cfg

logger = logging.getLogger(__name__)


@dataclass
class SendResult:
    success: bool
    provider_message_id: Optional[str]
    error: Optional[str] = None


async def send_whatsapp_message(to_phone: str, text: str) -> SendResult:
    """
    Send `text` to `to_phone` using the configured WhatsApp provider.
    `to_phone` should be in E.164 format, e.g. "+254712345678".
    """
    provider = cfg.whatsapp.get("provider", "cloud_api")
    if provider == "twilio":
        return await _send_twilio(to_phone, text)
    return await _send_cloud_api(to_phone, text)


# ── Meta WhatsApp Cloud API ───────────────────────────────────────────────────

async def _send_cloud_api(to_phone: str, text: str) -> SendResult:
    phone_number_id = cfg.whatsapp.get("phone_number_id", "")
    access_token    = cfg.whatsapp.get("access_token", "")
    api_version     = cfg.whatsapp.get("api_version", "v19.0")

    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone.lstrip("+"),
        "type": "text",
        "text": {"body": text},
    }

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            msg_id = data.get("messages", [{}])[0].get("id")
            logger.info("Cloud API sent to %s — msg_id=%s", to_phone, msg_id)
            return SendResult(success=True, provider_message_id=msg_id)
        except httpx.HTTPStatusError as exc:
            err = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            logger.error("Cloud API send failed: %s", err)
            return SendResult(success=False, provider_message_id=None, error=err)
        except Exception as exc:
            logger.error("Cloud API send exception: %s", exc)
            return SendResult(success=False, provider_message_id=None, error=str(exc))


# ── Twilio WhatsApp ───────────────────────────────────────────────────────────

async def _send_twilio(to_phone: str, text: str) -> SendResult:
    """
    Uses Twilio's REST API via httpx (avoids the synchronous twilio SDK).
    """
    account_sid = cfg.whatsapp.get("twilio_account_sid", "")
    auth_token  = cfg.whatsapp.get("twilio_auth_token", "")
    from_number = cfg.whatsapp.get("twilio_from_number", "whatsapp:+14155238886")

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    data = {
        "From": from_number,
        "To":   f"whatsapp:{to_phone}",
        "Body": text,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(url, data=data, auth=(account_sid, auth_token))
            resp.raise_for_status()
            result = resp.json()
            msg_id = result.get("sid")
            logger.info("Twilio sent to %s — sid=%s", to_phone, msg_id)
            return SendResult(success=True, provider_message_id=msg_id)
        except httpx.HTTPStatusError as exc:
            err = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            logger.error("Twilio send failed: %s", err)
            return SendResult(success=False, provider_message_id=None, error=err)
        except Exception as exc:
            logger.error("Twilio send exception: %s", exc)
            return SendResult(success=False, provider_message_id=None, error=str(exc))
