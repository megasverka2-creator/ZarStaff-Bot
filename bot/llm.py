"""Anthropic API bilan ishlash.

Uchta muhim narsa bu yerda hal qilinadi:

1. XARAJAT NAZORATI. Har so'rov pul. Cheklovsiz qo'ysangiz,
   bir kunda kutilmagan hisob kelishi mumkin. Har chaqiruvdan
   oldin kunlik limit tekshiriladi (bot/services.py).

2. GURUH XOTIRASI. Agentlar bir-birining javobini ko'radi -
   guruhning oxirgi xabarlari kontekst sifatida uzatiladi.
   Lekin faqat siz @ bilan chaqirganingizda javob beradi,
   aks holda cheksiz halqa boshlanadi.

3. QAYTA URINISH. Anthropic vaqti-vaqti bilan 429 (ko'p so'rov)
   yoki 529 (server band) qaytaradi. Bu o'tkinchi holat. Qayta
   urinmasak, bitta vaqtinchalik xato = yo'qolgan javob va
   guruhda "⚠️ Xato" yozuvi.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

from bot.config import settings

log = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

# Shu kodlarda qayta urinamiz - hammasi o'tkinchi.
RETRY_CODES = {408, 409, 429, 500, 502, 503, 504, 529}
MAX_ATTEMPTS = 3
BACKOFF = (2.0, 5.0)  # urinishlar orasidagi kutish, soniya

# 1 million token uchun narx, USD. 2026-yil avgust holatiga.
# Anthropic narxni o'zgartirsa shu yerni yangilang:
# platform.claude.com/docs/en/about-claude/pricing
PRICING = {
    "claude-opus-5": {"in": 5.0, "out": 25.0},
    "claude-sonnet-5": {"in": 2.0, "out": 10.0},
    "claude-haiku-4-5-20251001": {"in": 1.0, "out": 5.0},
}
DEFAULT_PRICE = {"in": 5.0, "out": 25.0}  # noma'lum model - eng qimmatini olamiz


@dataclass
class Reply:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    searched: bool = False

    def cost_usd(self) -> float:
        p = PRICING.get(self.model, DEFAULT_PRICE)
        return (
            self.input_tokens / 1_000_000 * p["in"]
            + self.output_tokens / 1_000_000 * p["out"]
        )


class AnthropicError(Exception):
    pass


def _headers() -> dict:
    return {
        "x-api-key": settings.anthropic_key,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }


def _payload(
    *,
    system: str,
    messages: list[dict],
    model: str,
    max_tokens: int,
    enable_search: bool,
) -> dict:
    payload: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    if enable_search:
        payload["tools"] = [
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 5,
            }
        ]
    return payload


def _retry_after(resp: httpx.Response, attempt: int) -> float:
    raw = resp.headers.get("retry-after")
    if raw:
        try:
            return min(float(raw), 30.0)
        except ValueError:
            pass
    return BACKOFF[min(attempt, len(BACKOFF) - 1)]


async def ask(
    *,
    system: str,
    messages: list[dict],
    model: str,
    max_tokens: int = 2000,
    enable_search: bool = False,
    on_chunk: Callable[[str], Awaitable[None]] | None = None,
) -> Reply:
    """Modeldan javob oladi.

    `on_chunk` berilsa javob oqim (streaming) rejimida olinadi va
    har yangi bo'lak shu funksiyaga uzatiladi — Opus 40-60 soniya
    o'ylaydi, foydalanuvchi bo'sh ekranga qarab o'tirmasin.
    """
    payload = _payload(
        system=system,
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        enable_search=enable_search,
    )

    last: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            if on_chunk is not None:
                return await _stream(payload, model, on_chunk)
            return await _once(payload, model)
        except _Retryable as e:
            last = e.reason
            if attempt == MAX_ATTEMPTS - 1:
                break
            log.warning(
                "Anthropic %s — %.0f soniyadan keyin qayta urinaman (%d/%d)",
                e, e.wait, attempt + 2, MAX_ATTEMPTS,
            )
            await asyncio.sleep(e.wait)
    raise AnthropicError(str(last) if last else "noma'lum xato")


class _Retryable(Exception):
    """Ichki signal: bu xatoda qayta urinsa bo'ladi."""

    def __init__(self, message: str, wait: float):
        super().__init__(message)
        self.wait = wait
        self.reason = AnthropicError(message)


async def _once(payload: dict, model: str) -> Reply:
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(API_URL, json=payload, headers=_headers())
    except (httpx.TimeoutException, httpx.TransportError) as e:
        raise _Retryable(f"tarmoq xatosi: {type(e).__name__}", BACKOFF[0])

    if resp.status_code in RETRY_CODES:
        raise _Retryable(
            f"API xatosi {resp.status_code}", _retry_after(resp, 0)
        )
    if resp.status_code != 200:
        raise AnthropicError(f"API xatosi {resp.status_code}: {resp.text[:400]}")

    data = resp.json()

    # Javob bir nechta blokdan iborat bo'lishi mumkin (matn, qidiruv).
    # Faqat matn bloklarini yig'amiz.
    parts = []
    searched = False
    for block in data.get("content", []):
        btype = block.get("type")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype in ("server_tool_use", "web_search_tool_result"):
            searched = True

    usage = data.get("usage", {})
    return Reply(
        text="\n".join(p for p in parts if p).strip() or "(bo'sh javob)",
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        model=model,
        searched=searched,
    )


async def _stream(
    payload: dict, model: str, on_chunk: Callable[[str], Awaitable[None]]
) -> Reply:
    """Oqim rejimi: matn yozilishi bilan qism-qism qaytaradi."""
    body = dict(payload, stream=True)
    parts: list[str] = []
    searched = False
    in_tokens = out_tokens = 0

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            async with client.stream(
                "POST", API_URL, json=body, headers=_headers()
            ) as resp:
                if resp.status_code != 200:
                    raw = (await resp.aread()).decode("utf-8", "replace")
                    if resp.status_code in RETRY_CODES:
                        raise _Retryable(
                            f"API xatosi {resp.status_code}",
                            _retry_after(resp, 0),
                        )
                    raise AnthropicError(
                        f"API xatosi {resp.status_code}: {raw[:400]}"
                    )

                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue

                    etype = event.get("type")
                    if etype == "message_start":
                        usage = event.get("message", {}).get("usage", {})
                        in_tokens = usage.get("input_tokens", 0)
                    elif etype == "content_block_start":
                        btype = event.get("content_block", {}).get("type")
                        if btype in ("server_tool_use", "web_search_tool_result"):
                            searched = True
                    elif etype == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            piece = delta.get("text", "")
                            parts.append(piece)
                            await on_chunk(piece)
                    elif etype == "message_delta":
                        out_tokens = event.get("usage", {}).get(
                            "output_tokens", out_tokens
                        )
                    elif etype == "error":
                        msg = event.get("error", {}).get("message", "oqim xatosi")
                        raise AnthropicError(msg)
    except (httpx.TimeoutException, httpx.TransportError) as e:
        # Matn qisman kelgan bo'lsa - qayta urinmaymiz, borini beramiz.
        if parts:
            log.warning("Oqim uzildi, qisman javob qaytarildi: %s", e)
        else:
            raise _Retryable(f"tarmoq xatosi: {type(e).__name__}", BACKOFF[0])

    return Reply(
        text="".join(parts).strip() or "(bo'sh javob)",
        input_tokens=in_tokens,
        output_tokens=out_tokens,
        model=model,
        searched=searched,
    )
