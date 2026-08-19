"""Avtomatik kunlik hisobot.

Har kuni belgilangan soatda guruhga taksi statistikasi yuboriladi:
kechagi holatga nisbatan o'sish va ko'rilmagan arizalar haqida
ogohlantirish.

NEGA KERAK. `/raqamlar` ni har kuni qo'lda yozish esdan chiqadi, eng
muhimi esa ariza: haydovchi ariza qoldirib, javob kutadi. Bir kun
javobsiz qolsa boshqa joyga ketadi. Hisobot buni har kuni ko'z
oldiga qo'yadi.

Bu yerda AI ishlatilmaydi — faqat bazadan o'qish. Ya'ni hisobot
kunlik limitni yemaydi.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import func, select

from bot.config import settings
from bot.db import Session
from bot.models import Snapshot, Usage
from bot.services import (
    TaxiNumbers,
    fmt_number,
    last_snapshot,
    save_snapshot,
    taxi_numbers,
)

log = logging.getLogger(__name__)

CHECK_EVERY = 60  # soniya


def _delta(now: int, before: int | None) -> str:
    """O'sishni ko'rsatadi: '1 240 (+38)'."""
    body = fmt_number(now)
    if before is None or now < 0 or before < 0:
        return body
    diff = now - before
    if diff == 0:
        return body
    sign = "+" if diff > 0 else "-"
    return f"{body} ({sign}{fmt_number(abs(diff))})"


async def _spent_between(start: datetime, end: datetime) -> float:
    async with Session() as session:
        result = await session.execute(
            select(func.coalesce(func.sum(Usage.cost_usd), 0.0)).where(
                Usage.created_at >= start, Usage.created_at < end
            )
        )
        return float(result.scalar_one())


def build_report(n: TaxiNumbers, prev: Snapshot | None, spent: float) -> str:
    today = datetime.now(settings.tz).strftime("%d.%m.%Y")
    lines = [f"🌅 <b>Kunlik hisobot</b> — {today}\n"]

    if not n.ok:
        lines.append(n.error or "Taksi bazasi o'qilmadi.")
    else:
        since = ""
        if prev is not None:
            days = (datetime.now(settings.tz).date()
                    - prev.created_at.astimezone(settings.tz).date()).days
            if days == 1:
                since = " (kechagiga nisbatan)"
            elif days > 1:
                since = f" ({days} kun oldingiga nisbatan)"

        lines.append(f"<b>Taksi</b>{since}")
        lines.append(
            f"Foydalanuvchilar: {_delta(n.users, prev.users if prev else None)}"
        )
        lines.append(
            f"Haydovchilar: {_delta(n.drivers, prev.drivers if prev else None)}"
            f" (onlayn: {fmt_number(n.online)})"
        )
        lines.append(
            f"Buyurtmalar: {_delta(n.orders, prev.orders if prev else None)}"
        )
        lines.append(
            f"Yakunlangan: {_delta(n.done, prev.done if prev else None)}"
        )
        lines.append(
            f"Aylanma: {_delta(n.revenue, prev.revenue if prev else None)} so'm"
        )

        if n.orders > 0 and n.done >= 0:
            lines.append(f"Yakunlanish darajasi: {n.done / n.orders * 100:.0f}%")

        # Eng muhim qatorni oxiriga qo'yamiz — ko'zga tashlansin.
        if n.pending_apps > 0:
            lines.append(
                f"\n⚠️ <b>{n.pending_apps} ta ariza javob kutmoqda.</b>\n"
                "Haydovchi bir kun javob olmasa boshqa joyga ketadi."
            )
        elif n.lost > 0 and n.orders > 0 and n.lost / n.orders > 0.2:
            lines.append(
                f"\n⚠️ Buyurtmalarning {n.lost / n.orders * 100:.0f}% ida "
                "haydovchi topilmagan. Onlayn haydovchi yetishmayapti."
            )

    lines.append(f"\n<i>Kechagi API sarfi: ${spent:.2f}</i>")
    return "\n".join(lines)


async def send_report(bot: Bot, chat_id: int) -> None:
    """Hisobotni yig'adi va yuboradi."""
    numbers = await taxi_numbers()
    prev = await last_snapshot()  # yangisini saqlashdan OLDIN olamiz

    now_local = datetime.now(settings.tz)
    day_start = now_local.replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    spent = await _spent_between(day_start - timedelta(days=1), day_start)

    text = build_report(numbers, prev, spent)
    await save_snapshot(numbers)
    await bot.send_message(chat_id, text, parse_mode="HTML")


async def scheduler(bot: Bot) -> None:
    """Fon vazifasi: har daqiqada vaqtni tekshiradi.

    Ikki qavat himoya, hisobot ikki marta ketmasin:
      1. Xotirada — shu ishga tushirishda yuborilgan sana;
      2. Bazada — oxirgi kesim sanasi (bot qayta ishga tushsa ham
         ishlaydi).
    """
    target = settings.report_target()
    if target is None:
        return

    log.info(
        "Kunlik hisobot yoqilgan: soat %02d:00 (UTC%+d), chat %s",
        settings.report_hour, settings.tz_offset_hours, target,
    )

    sent_on: date | None = None

    while True:
        try:
            now = datetime.now(settings.tz)
            if now.hour == settings.report_hour and sent_on != now.date():
                last = await last_snapshot()
                already = (
                    last is not None
                    and last.created_at.astimezone(settings.tz).date() == now.date()
                )
                if not already:
                    await send_report(bot, target)
                    log.info("Kunlik hisobot yuborildi: %s", now.date())
                sent_on = now.date()
        except TelegramAPIError as e:
            log.error("Hisobot yuborilmadi: %s", e)
            sent_on = datetime.now(settings.tz).date()  # qayta urinmaymiz
        except Exception:
            log.exception("Hisobotda kutilmagan xato")
            sent_on = datetime.now(settings.tz).date()

        await asyncio.sleep(CHECK_EVERY)
