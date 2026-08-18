"""Asosiy mantiq: xotira, xarajat nazorati, taksi statistikasi."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from bot.config import settings
from bot.db import Session
from bot.models import Message, Usage, utcnow

log = logging.getLogger(__name__)


# ------------------------------------------------------------ xotira

async def remember(
    chat_id: int,
    author: str,
    body: str,
    *,
    is_agent: bool = False,
    telegram_message_id: int | None = None,
) -> None:
    """Xabarni xotiraga yozadi."""
    if not body.strip():
        return
    async with Session() as session:
        session.add(
            Message(
                chat_id=chat_id,
                telegram_message_id=telegram_message_id,
                author=author[:64],
                is_agent=is_agent,
                text=body[:4000],
            )
        )
        await session.commit()


async def recall(chat_id: int, limit: int | None = None) -> list[Message]:
    """Guruhning oxirgi xabarlarini eskidan yangiga qaytaradi."""
    n = limit or settings.memory_messages
    async with Session() as session:
        result = await session.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.id.desc())
            .limit(n)
        )
        rows = list(result.scalars().all())
    return list(reversed(rows))


def build_messages(history: list[Message], question: str) -> list[dict]:
    """Suhbat tarixini API formatiga o'giradi.

    Butun guruh suhbatini BITTA user xabariga joylashtiramiz, keyin
    savolni qo'shamiz. Nega: guruhda ko'p ishtirokchi bor, ularni
    user/assistant juftligiga to'g'ri joylashtirib bo'lmaydi. Bu
    usul soddaroq va agent kim nima deganini aniq ko'radi.
    """
    if not history:
        return [{"role": "user", "content": question}]

    lines = []
    for m in history:
        tag = f"[{m.author}]" if m.is_agent else m.author
        lines.append(f"{tag}: {m.text}")

    transcript = "\n".join(lines)
    return [
        {
            "role": "user",
            "content": (
                "<guruh_suhbati>\n"
                "Bu ish guruhidagi oxirgi xabarlar. Kvadrat qavsdagilar — "
                "boshqa AI agentlarning javoblari, qolganlari odamlar.\n\n"
                f"{transcript}\n"
                "</guruh_suhbati>\n\n"
                "<savol>\n"
                f"{question}\n"
                "</savol>\n\n"
                "Yuqoridagi suhbatni hisobga olib javob ber. Boshqa agent "
                "aytgan fikrga qo'shilmasang — ochiq ayt va sababini tushuntir."
            ),
        }
    ]


# ------------------------------------------------------------ xarajat

async def spent_today() -> float:
    day_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    async with Session() as session:
        result = await session.execute(
            select(func.coalesce(func.sum(Usage.cost_usd), 0.0)).where(
                Usage.created_at >= day_start
            )
        )
        return float(result.scalar_one())


async def limit_reached() -> tuple[bool, float]:
    spent = await spent_today()
    return spent >= settings.daily_limit_usd, spent


async def log_usage(
    chat_id: int, user_id: int, agent: str, reply
) -> None:
    async with Session() as session:
        session.add(
            Usage(
                chat_id=chat_id,
                user_id=user_id,
                agent=agent,
                model=reply.model,
                input_tokens=reply.input_tokens,
                output_tokens=reply.output_tokens,
                cost_usd=reply.cost_usd(),
            )
        )
        await session.commit()


async def usage_report(days: int = 7) -> str:
    since = utcnow() - timedelta(days=days)
    async with Session() as session:
        total = float(
            (
                await session.execute(
                    select(func.coalesce(func.sum(Usage.cost_usd), 0.0)).where(
                        Usage.created_at >= since
                    )
                )
            ).scalar_one()
        )
        rows = (
            await session.execute(
                select(
                    Usage.agent,
                    func.count(Usage.id),
                    func.coalesce(func.sum(Usage.cost_usd), 0.0),
                )
                .where(Usage.created_at >= since)
                .group_by(Usage.agent)
                .order_by(func.sum(Usage.cost_usd).desc())
            )
        ).all()

    today = await spent_today()
    lines = [
        f"<b>Xarajat</b> (oxirgi {days} kun)\n",
        f"Bugun: ${today:.3f} / ${settings.daily_limit_usd:.2f}",
        f"Jami: ${total:.3f}\n",
    ]
    if rows:
        lines.append("Agentlar bo'yicha:")
        for agent, count, cost in rows:
            lines.append(f"  {agent}: {count} ta so'rov, ${cost:.3f}")
    else:
        lines.append("Hali so'rov bo'lmagan.")
    return "\n".join(lines)


# ------------------------------------------------------------ taksi statistikasi

async def taxi_stats() -> str:
    """Taksi botining bazasidan real raqamlar. FAQAT O'QISH.

    Agent noto'g'ri buyruq bersa ham real buyurtmalar o'chmasin
    deb, faqat SELECT ishlatiladi.
    """
    if not settings.taxi_database_url:
        return "Taksi bazasi ulanmagan (TAXI_DATABASE_URL berilmagan)."

    engine = create_async_engine(settings.taxi_database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            async def one(sql: str) -> int:
                try:
                    r = await conn.execute(text(sql))
                    return int(r.scalar_one() or 0)
                except Exception:
                    return -1  # jadval hali yaratilmagan

            users = await one("SELECT count(*) FROM users")
            drivers = await one("SELECT count(*) FROM drivers")
            online = await one(
                "SELECT count(*) FROM drivers WHERE is_online = true"
            )
            orders = await one("SELECT count(*) FROM orders")
            done = await one(
                "SELECT count(*) FROM orders WHERE status = 'completed'"
            )
            lost = await one(
                "SELECT count(*) FROM orders WHERE status = 'not_found'"
            )
            revenue = await one(
                "SELECT coalesce(sum(fare),0) FROM orders "
                "WHERE status = 'completed'"
            )
            apps = await one(
                "SELECT count(*) FROM driver_applications "
                "WHERE status = 'pending'"
            )
    except Exception as e:
        return f"Taksi bazasiga ulanib bo'lmadi: {e}"
    finally:
        await engine.dispose()

    def fmt(v: int) -> str:
        return "—" if v < 0 else f"{v:,}".replace(",", " ")

    conv = ""
    if orders > 0 and done >= 0:
        conv = f"\nYakunlanish darajasi: {done / orders * 100:.0f}%"

    return (
        "<b>Zarafshon Taxi — real raqamlar</b>\n\n"
        f"Foydalanuvchilar: {fmt(users)}\n"
        f"Haydovchilar: {fmt(drivers)} (onlayn: {fmt(online)})\n"
        f"Ko'rilmagan ariza: {fmt(apps)}\n\n"
        f"Buyurtmalar: {fmt(orders)}\n"
        f"Yakunlangan: {fmt(done)}\n"
        f"Haydovchi topilmadi: {fmt(lost)}\n"
        f"Aylanma: {fmt(revenue)} so'm{conv}"
    )
