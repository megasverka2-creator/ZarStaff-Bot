"""Anthropic API bilan ishlash.

Ikkita muhim narsa bu yerda hal qilinadi:

1. XARAJAT NAZORATI. Har so'rov pul. Cheklovsiz qo'ysangiz,
   bir kunda kutilmagan hisob kelishi mumkin. Har chaqiruvdan
   oldin kunlik limit tekshiriladi.

2. GURUH XOTIRASI. Agentlar bir-birining javobini ko'radi -
   guruhning oxirgi xabarlari kontekst sifatida uzatiladi.
   Lekin faqat siz @ bilan chaqirganingizda javob beradi,
   aks holda cheksiz halqa boshlanadi.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from bot.config import settings

log = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

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


async def ask(
    *,
    system: str,
    messages: list[dict],
    model: str,
    max_tokens: int = 2000,
    enable_search: bool = False,
) -> Reply:
    """Modeldan javob oladi."""
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

    headers = {
        "x-api-key": settings.anthropic_key,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }

    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(API_URL, json=payload, headers=headers)

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
