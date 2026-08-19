"""Guruhdagi xabarlarni qayta ishlash."""
from __future__ import annotations

import asyncio
import logging
import re
import time

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.types import Message as TgMessage

from bot.agents.roles import AGENTS, Agent, agent_list_text, find_agent
from bot.config import settings
from bot.format import plain, split_text, to_html
from bot.llm import AnthropicError, ask
from bot.media import MediaError, find_photo, find_voice, image_block, transcribe
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


# ---------------------------------------------------------------- yuborish

def agent_header(agent: Agent, mark: str = "") -> tuple[str, str]:
    """Javob sarlavhasi: (HTML, oddiy matn).

    Ikkalasi ham kerak — HTML ishlamay qolsa zaxira variantda
    foydalanuvchi `<b>` teglarini o'qib o'tirmasin.
    """
    return (
        f"{agent.emoji} <b>{agent.name}</b>{mark}\n\n",
        f"{agent.emoji} {agent.name}{mark}\n\n",
    )


async def _deliver(
    message: TgMessage, header: tuple[str, str], body: str
) -> None:
    """Javobni yuboradi: bo'laklab, HTML ga o'girib, xatosiz.

    Model matni markdown yozadi va kod ichida `<` bo'ladi. To'g'ridan
    to'g'ri yuborsak Telegram 400 qaytaradi va foydalanuvchi hech
    narsa ko'rmaydi. Shuning uchun: avval bo'laklaymiz (bo'linish
    teg o'rtasiga tushmasin), keyin har bo'lakni HTML ga o'giramiz,
    baribir xato bo'lsa oddiy matn bilan yuboramiz.
    """
    rich, bare = header
    chunks = split_text(body)
    for i, chunk in enumerate(chunks):
        send = message.reply if i == 0 else message.answer
        try:
            await send(
                (rich if i == 0 else "") + to_html(chunk), parse_mode="HTML"
            )
        except TelegramBadRequest as e:
            log.warning("HTML yuborilmadi (%s), oddiy matn bilan qayta", e)
            await send(
                (bare if i == 0 else "") + plain(chunk), parse_mode=None
            )
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            await send(
                (bare if i == 0 else "") + plain(chunk), parse_mode=None
            )
        if i + 1 < len(chunks):
            await asyncio.sleep(0.3)


class Streamer:
    """Javobni yozilishi bilan ko'rsatadi.

    Opus 40-60 soniya o'ylaydi. Oldin bu vaqt davomida guruhda
    "o'ylanmoqda…" turardi va odam bot qotib qolganmi deb o'ylardi.

    Telegram tez-tez tahrirlashni yoqtirmaydi, shuning uchun ikki
    chegara: kamida 2 soniya oralik va kamida 80 ta yangi belgi.
    Matn ekranga sig'may qolgach tahrirlash to'xtaydi — oxirgi
    javob baribir to'liq yuboriladi.
    """

    INTERVAL = 2.0
    GROWTH = 80
    PREVIEW = 3000

    def __init__(self, placeholder: TgMessage, header: str):
        self.placeholder = placeholder
        self.header = header
        self.parts: list[str] = []
        self.shown = 0
        self.last = time.monotonic()
        self.frozen = False

    async def feed(self, piece: str) -> None:
        self.parts.append(piece)
        if self.frozen:
            return
        size = sum(len(p) for p in self.parts)
        now = time.monotonic()
        if now - self.last < self.INTERVAL or size - self.shown < self.GROWTH:
            return
        self.last = now
        self.shown = size
        await self._paint()

    async def _paint(self) -> None:
        body = plain("".join(self.parts))
        if len(body) > self.PREVIEW:
            body = body[: self.PREVIEW]
            self.frozen = True  # sig'madi, endi faqat oxirgi javobni kutamiz
        try:
            # parse_mode=None — yarim yozilgan markdown HTML ni buzadi.
            await self.placeholder.edit_text(
                f"{self.header}{body}▌", parse_mode=None
            )
        except TelegramRetryAfter as e:
            self.last = time.monotonic() + e.retry_after
        except TelegramBadRequest:
            pass  # "message is not modified" va shunga o'xshash - muhim emas


# ---------------------------------------------------------------- buyruqlar

@router.message(CommandStart())
async def start(message: TgMessage) -> None:
    if not _allowed(message):
        await message.answer("Bu bot yopiq.")
        return
    extra = []
    if settings.report_enabled:
        extra.append(
            f"Kunlik hisobot: har kuni soat {settings.report_hour:02d}:00"
        )
    if settings.voice_enabled:
        extra.append("Ovozli xabar: yoqilgan")
    tail = ("\n\n<i>" + " · ".join(extra) + "</i>") if extra else ""

    await message.answer(
        "🧠 <b>Zarafshon Taxi — ishchi guruh</b>\n\n"
        "Agentni @ bilan chaqiring:\n\n"
        f"{agent_list_text()}\n\n"
        "◆ = kuchliroq model (qimmatroq)\n\n"
        "<b>Buyruqlar</b>\n"
        "/kengash — savolni bir necha agentga birdan berish\n"
        "/raqamlar — taksi botidan real statistika\n"
        "/hisobot — kunlik hisobotni hozir ko'rish\n"
        "/xarajat — API sarfi\n"
        "/id — shu chat ID si\n"
        "/tozala — guruh xotirasini tozalash\n\n"
        "<b>Rasm va reply</b>\n"
        "Rasmga izoh qilib <code>@kreativ</code> yozsangiz — agent "
        "rasmni ko'radi.\n"
        "Xabarga reply qilib chaqirsangiz — o'sha xabarni ko'radi.\n\n"
        "<i>Misol:</i>\n"
        "<code>@marketolog haydovchilar uchun e'lon matni yoz</code>"
        f"{tail}",
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


@router.message(Command("hisobot"))
async def report_cmd(message: TgMessage, bot: Bot) -> None:
    """Kunlik hisobotni qo'lda chaqirish.

    Avtomatik yuborilishini kutmasdan hozir ko'rish uchun.
    """
    if not _allowed(message):
        return
    from bot.reports import send_report

    await send_report(bot, message.chat.id)


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

    question = (message.text or "").split(maxsplit=1)
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
    council_agents = [
        a for a in AGENTS if a.key in ("mahsulot", "marketolog", "analitik")
    ]

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
            await _deliver(message, agent_header(agent), reply.text)
        except AnthropicError as e:
            log.error("Kengash xatosi %s: %s", agent.key, e)
            await message.answer(f"{agent.emoji} {agent.name}: xato — {e}")
        await asyncio.sleep(0.5)

    try:
        await status.delete()
    except Exception:
        pass


# ---------------------------------------------------------------- agent ishga tushirish

def _strip_mention(text: str, agent: Agent) -> str:
    """Savoldan @nomni olib tashlaydi (katta-kichik harfga qaramay)."""
    out = text
    # Uzun nomdan boshlaymiz: "@kod" ni oldin olib tashlasak
    # "@kodchi" dan "chi" qolib ketardi.
    for name in sorted(agent.all_names(), key=len, reverse=True):
        out = re.sub(rf"@{re.escape(name)}\b", " ", out, flags=re.IGNORECASE)
    return " ".join(out.split())


def _replied_context(message: TgMessage) -> str | None:
    """Reply qilingan xabar matni.

    Bu oxirgi 25 ta xabarga sig'magan bo'lishi mumkin (eski xabarga
    reply qilinsa), shuning uchun alohida uzatiladi.
    """
    src = message.reply_to_message
    if src is None:
        return None
    body = src.text or src.caption
    if not body:
        return None
    who = "agent" if (src.from_user and src.from_user.is_bot) else "odam"
    name = src.from_user.full_name if src.from_user else "noma'lum"
    return f"{name} ({who}): {body}"


async def _collect_images(bot: Bot, message: TgMessage) -> list[dict]:
    """Xabardagi va reply qilingan xabardagi rasmlar."""
    found = []
    for src in (message, message.reply_to_message):
        if src is None:
            continue
        photo = find_photo(src)
        if photo:
            found.append(photo)
    blocks = []
    for file_id, mime in found[:2]:  # ikkitadan ko'pi kerak emas, qimmat
        try:
            blocks.append(await image_block(bot, file_id, mime))
        except MediaError as e:
            log.warning("Rasm olinmadi: %s", e)
        except Exception:
            log.exception("Rasm yuklashda xato")
    return blocks


async def run_agent(
    message: TgMessage, bot: Bot, agent: Agent, question: str
) -> None:
    """Agentni chaqiradi va javobni guruhga yuboradi."""
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

    images = await _collect_images(bot, message)
    replied = _replied_context(message)

    # Bazadan raqam kerak bo'lsa - qo'shib beramiz
    extra = ""
    if agent.needs_db:
        stats = await taxi_stats()
        extra = f"\n\n<real_raqamlar>\n{stats}\n</real_raqamlar>"

    note = " 🖼" if images else ""
    placeholder = await message.reply(
        f"{agent.emoji} {agent.name} o'ylanmoqda…{note}"
    )
    streamer = Streamer(placeholder, f"{agent.emoji} {agent.name}\n\n")

    try:
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        reply = await ask(
            system=agent.system_prompt() + extra,
            messages=build_messages(
                history, question, replied=replied, images=images
            ),
            model=agent.model,
            enable_search=agent.needs_search,
            on_chunk=streamer.feed if settings.stream else None,
        )
    except AnthropicError as e:
        log.error("API xatosi: %s", e)
        await placeholder.edit_text(f"⚠️ Xato: {e}", parse_mode=None)
        return
    except Exception as e:
        log.exception("Kutilmagan xato")
        await placeholder.edit_text(
            f"⚠️ Kutilmagan xato: {type(e).__name__}", parse_mode=None
        )
        return

    await log_usage(message.chat.id, message.from_user.id, agent.key, reply)
    await remember(message.chat.id, agent.key, reply.text, is_agent=True)

    mark = (" 🔎" if reply.searched else "") + note
    rich, bare = agent_header(agent, mark)
    chunks = split_text(reply.text)

    # Bitta bo'lakka sig'sa - "o'ylanmoqda" xabarining o'zini
    # to'ldiramiz. Guruhda ortiqcha xabar qolmaydi.
    if len(chunks) == 1:
        try:
            await placeholder.edit_text(
                rich + to_html(chunks[0]), parse_mode="HTML"
            )
            return
        except TelegramBadRequest as e:
            log.warning("HTML tahrirlanmadi (%s), oddiy matn bilan", e)
            try:
                await placeholder.edit_text(
                    bare + plain(chunks[0]), parse_mode=None
                )
                return
            except TelegramBadRequest:
                pass

    try:
        await placeholder.delete()
    except Exception:
        pass
    await _deliver(message, (rich, bare), reply.text)


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

    question = _strip_mention(message.text, agent)
    if not question:
        # Reply qilib faqat "@texnik" deb yozish - o'sha xabar haqida
        # so'ralgan degani.
        if message.reply_to_message is not None:
            question = "Yuqoridagi xabarga sharh ber."
        else:
            await message.reply(f"{agent.emoji} Savolni ham yozing.")
            return

    await run_agent(message, bot, agent, question)


# ---------------------------------------------------------------- rasm

@router.message(F.photo | F.document)
async def photo(message: TgMessage, bot: Bot) -> None:
    """Rasmli xabar.

    Izohda agent chaqirilsa — agent rasmni ko'radi. Chaqirilmasa
    xotiraga yozib qo'yamiz, keyin kimdir so'rasa kontekst bo'ladi.
    """
    if not _allowed(message):
        return

    caption = message.caption or ""
    agent = find_agent(caption)
    if agent is None:
        if find_photo(message):
            await remember(
                message.chat.id,
                _author(message),
                f"[rasm yubordi] {caption}".strip(),
                telegram_message_id=message.message_id,
            )
        return

    question = _strip_mention(caption, agent) or "Bu rasmga baho ber."
    await run_agent(message, bot, agent, question)


# ---------------------------------------------------------------- ovoz

@router.message(F.voice | F.audio | F.video_note)
async def voice(message: TgMessage, bot: Bot) -> None:
    """Ovozli xabar.

    Matnga o'giriladi, keyin oddiy xabar kabi ishlanadi — ichida
    @agent bo'lsa agent chaqiriladi, bo'lmasa xotiraga tushadi.

    Anthropic audio tushunmaydi, shuning uchun transkripsiya alohida
    xizmat orqali bo'ladi. Sozlanmagan bo'lsa jim o'tamiz — har
    ovozli xabarga "sozlanmagan" deb javob berish bezor qiladi.
    """
    if not _allowed(message):
        return
    if not settings.voice_enabled:
        return

    found = find_voice(message)
    if found is None:
        return
    file_id, filename = found

    try:
        text = await transcribe(bot, file_id, filename)
    except MediaError as e:
        log.warning("Transkripsiya bo'lmadi: %s", e)
        return
    except Exception:
        log.exception("Transkripsiyada kutilmagan xato")
        return

    agent = find_agent(text)
    if agent is None:
        await remember(
            message.chat.id,
            _author(message),
            f"[ovozli xabar] {text}",
            telegram_message_id=message.message_id,
        )
        return

    await message.reply(f"🎙 <i>{to_html(text)}</i>", parse_mode="HTML")
    question = _strip_mention(text, agent)
    if not question:
        question = "Yuqoridagi so'rovga javob ber."
    await run_agent(message, bot, agent, question)


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
