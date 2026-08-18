"""Guruhdagi xabarlarni qayta ishlash."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import Message as TgMessage

from bot.agents.roles import AGENTS, agent_list_text, find_agent
from bot.config import settings
from bot.llm import AnthropicError, ask
from bot.services import (
    build_messages,
    limit_reached,
    log_usage,
    recall,
    remember,
    taxi_stats,
    usage_report,
)

log = logging.getLogger(__name__)
router = Router(name="staff")

MAX_TG = 4000  # Telegram xabar chegarasi


def _allowed(message: TgMessage) -> bool:
    """Kim ishlata oladi.

    Bu bot pul sarflaydi, shuning uchun ruxsat qat'iy.
    """
    if message.from_user is None:
        return False
    if message.from_user.id not in settings.allowed_users:
        return False
    if settings.allowed_chats and message.chat.id not in settings.allowed_chats:
        return False
    return True


def _author(message: TgMessage) -> str:
    u = message.from_user
    if u is None:
        return "noma'lum"
    return u.full_name or u.username or str(u.id)


async def _send_long(message: TgMessage, body: str, **kw) -> None:
    """Uzun javobni bo'laklab yuboradi."""
    if len(body) <= MAX_TG:
        await message.reply(body, **kw)
        return
    chunks, current = [], ""
    for para in body.split("\n\n"):
        if len(current) + len(para) + 2 > MAX_TG:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    for i, chunk in enumerate(chunks):
        if i == 0:
            await message.reply(chunk, **kw)
        else:
            await message.answer(chunk, **kw)


# ---------------------------------------------------------------- buyruqlar

@router.message(CommandStart())
async def start(message: TgMessage) -> None:
    if not _allowed(message):
        await message.answer("Bu bot yopiq.")
        return
    await message.answer(
        "🧠 <b>Zarafshon Taxi — ishchi guruh</b>\n\n"
        "Agentni @ bilan chaqiring:\n\n"
        f"{agent_list_text()}\n\n"
        "◆ = kuchliroq model (qimmatroq)\n\n"
        "<b>Buyruqlar</b>\n"
        "/kengash — savolni bir necha agentga birdan berish\n"
        "/raqamlar — taksi botidan real statistika\n"
        "/xarajat — API sarfi\n"
        "/id — shu chat ID si\n"
        "/tozala — guruh xotirasini tozalash\n\n"
        "<i>Misol:</i>\n"
        "<code>@marketolog haydovchilar uchun e'lon matni yoz</code>",
        parse_mode="HTML",
    )


@router.message(Command("id"))
async def chat_id(message: TgMessage) -> None:
    await message.answer(
        f"Chat ID: <code>{message.chat.id}</code>\n"
        f"Sizning ID: <code>{message.from_user.id}</code>",
        parse_mode="HTML",
    )


@router.message(Command("agentlar", "help"))
async def agents_cmd(message: TgMessage) -> None:
    if not _allowed(message):
        return
    await message.answer(agent_list_text(), parse_mode="HTML")


@router.message(Command("xarajat"))
async def cost_cmd(message: TgMessage) -> None:
    if not _allowed(message):
        return
    await message.answer(await usage_report(), parse_mode="HTML")


@router.message(Command("raqamlar"))
async def numbers_cmd(message: TgMessage) -> None:
    if not _allowed(message):
        return
    await message.answer(await taxi_stats(), parse_mode="HTML")


@router.message(Command("tozala"))
async def clear_cmd(message: TgMessage) -> None:
    if not _allowed(message):
        return
    from sqlalchemy import delete

    from bot.db import Session
    from bot.models import Message as Msg

    async with Session() as session:
        await session.execute(delete(Msg).where(Msg.chat_id == message.chat.id))
        await session.commit()
    await message.answer("Guruh xotirasi tozalandi.")


# ---------------------------------------------------------------- kengash

@router.message(Command("kengash"))
async def council(message: TgMessage, bot: Bot) -> None:
    """Bitta savolni bir nechta agentga birdan berish.

    Har bir agent boshqalarnikini KO'RMAYDI - mustaqil fikr olamiz.
    Ular bir-birini o'qishini istasangiz, keyin @ bilan chaqiring.
    """
    if not _allowed(message):
        return

    question = message.text.split(maxsplit=1)
    if len(question) < 2:
        await message.reply(
            "Savolni yozing:\n"
            "<code>/kengash 6000 so'm narx to'g'rimi?</code>",
            parse_mode="HTML",
        )
        return
    q = question[1]

    over, spent = await limit_reached()
    if over:
        await message.reply(
            f"⚠️ Kunlik limit tugadi (${spent:.2f}). Ertaga qayta urining "
            f"yoki DAILY_LIMIT_USD ni oshiring."
        )
        return

    # Kengashga faqat strategik agentlar - hammasi emas, qimmat bo'ladi
    council_agents = [a for a in AGENTS if a.key in ("mahsulot", "marketolog", "analitik")]

    await remember(message.chat.id, _author(message), q,
                   telegram_message_id=message.message_id)
    history = await recall(message.chat.id)

    status = await message.reply(
        f"🏛 Kengash: {', '.join(a.name for a in council_agents)}\nO'ylanmoqda..."
    )

    for agent in council_agents:
        try:
            await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
            reply = await ask(
                system=agent.system_prompt(),
                messages=build_messages(history, q),
                model=agent.model,
                enable_search=False,  # kengashda qidiruv yo'q - tez bo'lsin
            )
            await log_usage(message.chat.id, message.from_user.id, agent.key, reply)
            await remember(message.chat.id, agent.key, reply.text, is_agent=True)
            await message.answer(
                f"{agent.emoji} <b>{agent.name}</b>\n\n{reply.text}",
                parse_mode="HTML",
            )
        except AnthropicError as e:
            log.error("Kengash xatosi %s: %s", agent.key, e)
            await message.answer(f"{agent.emoji} {agent.name}: xato — {e}")
        await asyncio.sleep(0.5)

    try:
        await status.delete()
    except Exception:
        pass


# ---------------------------------------------------------------- @agent

@router.message(F.text.contains("@"))
async def mention(message: TgMessage, bot: Bot) -> None:
    """Agentni @ bilan chaqirish.

    MUHIM: agent faqat shu yerda javob beradi. O'z-o'zidan gapirmaydi,
    aks holda agentlar bir-biriga cheksiz javob berib, pulni yeb
    qo'yadi.
    """
    if not _allowed(message):
        return

    agent = find_agent(message.text or "")
    if agent is None:
        return  # boshqa @ - bizga aloqasi yo'q

    # @nomni savoldan olib tashlaymiz
    question = message.text
    for name in agent.all_names():
        question = question.replace(f"@{name}", "").replace(f"@{name.title()}", "")
    question = question.strip()

    if not question:
        await message.reply(f"{agent.emoji} Savolni ham yozing.")
        return

    over, spent = await limit_reached()
    if over:
        await message.reply(
            f"⚠️ Kunlik limit tugadi (${spent:.2f} / "
            f"${settings.daily_limit_usd:.2f})."
        )
        return

    await remember(message.chat.id, _author(message), question,
                   telegram_message_id=message.message_id)
    history = await recall(message.chat.id)

    # Bazadan raqam kerak bo'lsa - qo'shib beramiz
    extra = ""
    if agent.needs_db:
        stats = await taxi_stats()
        extra = f"\n\n<real_raqamlar>\n{stats}\n</real_raqamlar>"

    thinking = await message.reply(f"{agent.emoji} {agent.name} o'ylanmoqda…")

    try:
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        reply = await ask(
            system=agent.system_prompt() + extra,
            messages=build_messages(history, question),
            model=agent.model,
            enable_search=agent.needs_search,
        )
    except AnthropicError as e:
        log.error("API xatosi: %s", e)
        await thinking.edit_text(f"⚠️ Xato: {e}")
        return
    except Exception as e:
        log.exception("Kutilmagan xato")
        await thinking.edit_text(f"⚠️ Kutilmagan xato: {type(e).__name__}")
        return

    await log_usage(message.chat.id, message.from_user.id, agent.key, reply)
    await remember(message.chat.id, agent.key, reply.text, is_agent=True)

    try:
        await thinking.delete()
    except Exception:
        pass

    mark = " 🔎" if reply.searched else ""
    header = f"{agent.emoji} <b>{agent.name}</b>{mark}\n\n"
    await _send_long(message, header + reply.text, parse_mode="HTML")


# ---------------------------------------------------------------- passiv xotira

@router.message(F.text)
async def listen(message: TgMessage) -> None:
    """Oddiy xabarlarni xotiraga yozadi, javob bermaydi.

    Shuning uchun agent keyinroq chaqirilganda guruhda nima
    gaplashilganini biladi.
    """
    if not _allowed(message):
        return
    if message.text.startswith("/"):
        return
    await remember(
        message.chat.id,
        _author(message),
        message.text,
        telegram_message_id=message.message_id,
    )
