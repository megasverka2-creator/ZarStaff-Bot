"""Rasm va ovozli xabar bilan ishlash.

RASM. Claude rasmni to'g'ridan-to'g'ri tushunadi — faylni yuklab olib,
base64 qilib so'rovga qo'shamiz. Shu bilan @kreativ logotip eskizini
ko'radi, @texnik esa xato skrinshotini.

OVOZ. Bu yerda cheklov bor: Anthropic API audio qabul qilmaydi.
Shuning uchun ovoz avval matnga o'giriladi — buning uchun alohida
xizmat kerak (Whisper bilan mos keladigan har qanday endpoint).
VOICE_API_URL berilmasa ovozli xabar shunchaki e'tiborsiz qoladi,
bot xato bermaydi.
"""
from __future__ import annotations

import base64
import io
import logging

import httpx
from aiogram import Bot
from aiogram.types import Message as TgMessage

from bot.config import settings

log = logging.getLogger(__name__)

# Anthropic rasm chegarasi 5 MB. Telegram siqilgan rasmi undan ancha
# kichik, lekin hujjat sifatida yuborilgani katta bo'lishi mumkin.
MAX_IMAGE_BYTES = 4_500_000
MAX_VOICE_BYTES = 20_000_000  # ~20 daqiqa ovoz

ALLOWED_IMAGE_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
}


class MediaError(Exception):
    pass


async def _download(bot: Bot, file_id: str, cap: int) -> bytes:
    file = await bot.get_file(file_id)
    if file.file_size and file.file_size > cap:
        raise MediaError(
            f"Fayl juda katta ({file.file_size / 1_000_000:.1f} MB, "
            f"chegara {cap / 1_000_000:.0f} MB)."
        )
    buf = io.BytesIO()
    await bot.download_file(file.file_path, buf)
    return buf.getvalue()


def find_photo(message: TgMessage) -> tuple[str, str] | None:
    """Xabardagi rasmni topadi: (file_id, mime_type).

    Ikki xil bo'ladi: siqilgan rasm (`photo`) va hujjat sifatida
    yuborilgan rasm (`document`). Ikkinchisi dizayn ishida ko'p
    uchraydi — sifat yo'qolmasin deb shunday yuboriladi.
    """
    if message.photo:
        return message.photo[-1].file_id, "image/jpeg"  # eng kattasi
    doc = message.document
    if doc and doc.mime_type in ALLOWED_IMAGE_TYPES:
        return doc.file_id, doc.mime_type
    return None


async def image_block(bot: Bot, file_id: str, mime: str) -> dict:
    """Rasmni Anthropic so'rovi uchun blokka aylantiradi."""
    data = await _download(bot, file_id, MAX_IMAGE_BYTES)
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": mime,
            "data": base64.standard_b64encode(data).decode("ascii"),
        },
    }


def find_voice(message: TgMessage) -> tuple[str, str] | None:
    """Ovozli xabar yoki audio: (file_id, fayl nomi)."""
    if message.voice:
        return message.voice.file_id, "voice.ogg"
    if message.audio:
        name = message.audio.file_name or "audio.mp3"
        return message.audio.file_id, name
    if message.video_note:
        return message.video_note.file_id, "note.mp4"
    return None


async def transcribe(bot: Bot, file_id: str, filename: str) -> str:
    """Ovozni matnga o'giradi.

    Whisper bilan mos keladigan endpointga yuboriladi. Anthropic
    audio tushunmagani uchun bu qadam majburiy — bo'lmasa ovozli
    xabar umuman ishlamaydi.
    """
    if not settings.voice_enabled:
        raise MediaError(
            "Ovozli xabar sozlanmagan. VOICE_API_URL va VOICE_API_KEY "
            "ni .env ga qo'shing."
        )

    data = await _download(bot, file_id, MAX_VOICE_BYTES)

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            settings.voice_api_url,
            headers={"Authorization": f"Bearer {settings.voice_api_key}"},
            files={"file": (filename, data)},
            data={"model": settings.voice_model},
        )

    if resp.status_code != 200:
        raise MediaError(
            f"Transkripsiya xatosi {resp.status_code}: {resp.text[:200]}"
        )

    try:
        text = resp.json().get("text", "")
    except ValueError:
        text = resp.text

    text = (text or "").strip()
    if not text:
        raise MediaError("Ovozdan matn chiqmadi.")
    return text
