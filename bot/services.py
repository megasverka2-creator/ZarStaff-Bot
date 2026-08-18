"""Asosiy mantiq: xotira, xarajat nazorati, taksi statistikasi."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from bot.config import settings
from bot.db import Session
from bot.models import Message, Snapshot, Usage, utcnow

log = logging.getLogger(__name__)


def local_day_start() -> datetime:
    """Mahalliy yarim tun, UTC da.

    UTC bo'yicha hisoblasak kunlik limit Toshkent vaqti bilan
    soat 05:00 da yangilanadi — ya'ni kechqurun sarflangan pul
    ertalabgacha limitni band qilib turadi.
    """
    now_local = datetime.now(settings.tz)
    midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc)


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


def build_messages(
    history: list[Message],
    question: str,
    *,
    replied: str | None = None,
    images: list[dict] | None = None,
) -> list[dict]:
    """Suhbat tarixini API formatiga o'giradi.

    Butun guruh suhbatini BITTA user xabariga joylashtiramiz, keyin
    savolni qo'shamiz. Nega: guruhda ko'p ishtirokchi bor, ularni
    user/assistant juftligiga to'g'ri joylashtirib bo'lmaydi. Bu
    usul soddaroq va agent kim nima deganini aniq ko'radi.

    `replied` — foydalanuvchi qaysi xabarga reply qilgani. Bu oxirgi
    25 ta xabarga sig'masligi mumkin (eski xabarga reply qilinsa),
    shuning uchun alohida uzatiladi.

    `images` — so'rovga qo'shiladigan rasm bloklari.
    """
    parts: list[str] = []

    if history:
        lines = []
        for m in history:
            tag = f"[{m.author}]" if m.is_agent else m.author
            lines.append(f"{tag}: {m.text}")
        parts.append(
            "<guruh_suhbati>\n"
            "Bu ish guruhidagi oxirgi xabarlar. Kvadrat qavsdagilar — "
            "boshqa AI agentlarning javoblari, qolganlari odamlar.\n\n"
            + "\n".join(lines)
            + "\n</guruh_suhbati>"
        )

    if replied:
        parts.append(
            "<javob_berilayotgan_xabar>\n"
            f"{replied[:3000]}\n"
            "</javob_berilayotgan_xabar>\n"
            "Savol aynan shu xabarga tegishli."
        )

    if images:
        parts.append(
            "<rasm>\nYuqorida biriktirilgan rasm(lar) savolga tegishli.\n"
            "</rasm>"
        )

    parts.append(f"<savol>\n{question}\n</savol>")

    if history:
        parts.append(
            "Yuqoridagi suhbatni hisobga olib javob ber. Boshqa agent "
            "aytgan fikrga qo'shilmasang — ochiq ayt va sababini tushuntir."
        )

    prompt = "\n\n".join(parts)

    if not images:
        return [{"role": "user", "content": prompt}]

    # Rasm matndan oldin turishi kerak — model shunda yaxshiroq bog'laydi.
    return [{"role": "user", "content": [*images, {"type": "text", "text": prompt}]}]


# ------------------------------------------------------------ xarajat

async def spent_today() -> float:
    day_start = local_day_start()
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

# Engine kesh. Ilgari har `@analitik` chaqirig'ida yangi Postgres
# ulanish ochilib yopilardi — bu sekin va Railway'da ulanish limitini
# yeydi. Endi bitta engine butun ish davomida saqlanadi.
_taxi_engine: AsyncEngine | None = None


def taxi_engine() -> AsyncEngine | None:
    global _taxi_engine
    if not settings.taxi_database_url:
        return None
    if _taxi_engine is None:
        _taxi_engine = create_async_engine(
            settings.taxi_database_url,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=0,
        )
    return _taxi_engine


async def close_taxi_engine() -> None:
    global _taxi_engine
    if _taxi_engine is not None:
        await _taxi_engine.dispose()
        _taxi_engine = None


@dataclass
class TaxiNumbers:
    """Taksi bazasidagi holat. -1 = jadval yo'q yoki o'qib bo'lmadi."""
    users: int = -1
    drivers: int = -1
    online: int = -1
    orders: int = -1
    done: int = -1
    lost: int = -1
    revenue: int = -1
    pending_apps: int = -1
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


async def taxi_numbers() -> TaxiNumbers:
    """Taksi botining bazasidan real raqamlar. FAQAT O'QISH.

    Agent noto'g'ri buyruq bersa ham real buyurtmalar o'chmasin
    deb, faqat SELECT ishlatiladi.
    """
    engine = taxi_engine()
    if engine is None:
        return TaxiNumbers(
            error="Taksi bazasi ulanmagan (TAXI_DATABASE_URL berilmagan)."
        )

    try:
        async with engine.connect() as conn:
            async def one(sql: str) -> int:
                try:
                    r = await conn.execute(text(sql))
                    return int(r.scalar_one() or 0)
                except Exception:
                    return -1  # jadval hali yaratilmagan

                
            return TaxiNumbers(
                users=await one("SELECT count(*) FROM users"),
                drivers=await one("SELECT count(*) FROM drivers"),
                online=await one(
                    "SELECT count(*) FROM drivers WHERE is_online = true"
                ),
                orders=await one("SELECT count(*) FROM orders"),
                done=await one(
                    "SELECT count(*) FROM orders WHERE status = 'completed'"
                ),
                lost=await one(
                    "SELECT count(*) FROM orders WHERE status = 'not_found'"
                ),
                revenue=await one(
                    "SELECT coalesce(sum(fare),0) FROM orders "
                    "WHERE status = 'completed'"
                ),
                pending_apps=await one(
                    "SELECT count(*) FROM driver_applications "
                    "WHERE status = 'pending'"
                ),
            )
    except Exception as e:
        log.warning("Taksi bazasi o'qilmadi: %s", e)
        return TaxiNumbers(error=f"Taksi bazasiga ulanib bo'lmadi: {e}")


def fmt_number(v: int) -> str:
    return "—" if v < 0 else f"{v:,}".replace(",", " ")


def taxi_stats_text(n: TaxiNumbers) -> str:
    if not n.ok:
        return n.error or "Noma'lum xato."

    conv = ""
    if n.orders > 0 and n.done >= 0:
        conv = f"\nYakunlanish darajasi: {n.done / n.orders * 100:.0f}%"

    return (
        "<b>Zarafshon Taxi — real raqamlar</b>\n\n"
        f"Foydalanuvchilar: {fmt_number(n.users)}\n"
        f"Haydovchilar: {fmt_number(n.drivers)} (onlayn: {fmt_number(n.online)})\n"
        f"Ko'rilmagan ariza: {fmt_number(n.pending_apps)}\n\n"
        f"Buyurtmalar: {fmt_number(n.orders)}\n"
        f"Yakunlangan: {fmt_number(n.done)}\n"
        f"Haydovchi topilmadi: {fmt_number(n.lost)}\n"
        f"Aylanma: {fmt_number(n.revenue)} so'm{conv}"
    )


async def taxi_stats() -> str:
    """Agentga va /raqamlar buyrug'iga beriladigan matn."""
    return taxi_stats_text(await taxi_numbers())


# ------------------------------------------------------------ kunlik kesim

async def save_snapshot(n: TaxiNumbers) -> Snapshot | None:
    """Bugungi raqamlarni saqlaydi — ertaga o'sishni ko'rsatish uchun.

    Taksi bazasi o'sish tarixini saqlamaydi (faqat joriy holat), shuning
    uchun kesimni o'zimiz yozib boramiz.
    """
    if not n.ok:
        return None
    row = Snapshot(
        users=n.users,
        drivers=n.drivers,
        orders=n.orders,
        done=n.done,
        revenue=n.revenue,
        pending_apps=n.pending_apps,
    )
    async with Session() as session:
        session.add(row)
        await session.commit()
    return row


async def last_snapshot() -> Snapshot | None:
    async with Session() as session:
        result = await session.execute(
            select(Snapshot).order_by(Snapshot.id.desc()).limit(1)
        )
        return result.scalars().first()
