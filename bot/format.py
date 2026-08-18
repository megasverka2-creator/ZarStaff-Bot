"""Model javobini Telegram HTML ga o'girish.

NEGA BU FAYL BOR. Model javobi markdown yozadi (`**qalin**`, kod
bloklari) va kod ichida `<`, `>`, `&` belgilari bo'ladi. Buni to'g'ridan
to'g'ri `parse_mode="HTML"` bilan yuborsak, Telegram
`400: can't parse entities` qaytaradi va foydalanuvchi HECH NARSA
ko'rmaydi — pul esa allaqachon sarflangan. @texnik kod yozganda bu
deyarli har safar sodir bo'ladi.

Shuning uchun: avval hamma narsa ekranlanadi, keyin faqat biz
ruxsat bergan markdown teglarga aylantiriladi. Model nima yozsa ham
natija to'g'ri HTML bo'ladi.
"""
from __future__ import annotations

import html
import re

MAX_TG = 3900  # Telegram chegarasi 4096; sarlavha uchun joy qoldiramiz

# Ekranlashdan omon qoladigan belgi. Model matnida uchramaydi.
_MARK = "\x00{}\x00"

_FENCE = re.compile(r"```(\w*)\n?(.*?)```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_BOLD_ALT = re.compile(r"__(.+?)__", re.DOTALL)
_ITALIC = re.compile(r"(?<![\w*])\*([^*\n]+?)\*(?![\w*])")
_ITALIC_ALT = re.compile(r"(?<![\w_])_([^_\n]+?)_(?![\w_])")
_STRIKE = re.compile(r"~~(.+?)~~", re.DOTALL)
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_HEADER = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*$", re.MULTILINE)
_BULLET = re.compile(r"^(\s*)[-*+]\s+", re.MULTILINE)
_HR = re.compile(r"^\s*([-*_])\1{2,}\s*$", re.MULTILINE)


def to_html(text: str) -> str:
    """Markdown matnni Telegram uchun xavfsiz HTML ga o'giradi."""
    if not text:
        return ""

    vault: list[str] = []

    def stash(payload: str) -> str:
        vault.append(payload)
        return _MARK.format(len(vault) - 1)

    # 1. Kod bloklari — ichidagi hamma narsa matn, markdown emas.
    def fence(m: re.Match) -> str:
        lang, body = m.group(1), m.group(2).rstrip("\n")
        escaped = html.escape(body)
        if lang:
            return stash(
                f'<pre><code class="language-{html.escape(lang)}">'
                f"{escaped}</code></pre>"
            )
        return stash(f"<pre>{escaped}</pre>")

    text = _FENCE.sub(fence, text)
    text = _INLINE_CODE.sub(
        lambda m: stash(f"<code>{html.escape(m.group(1))}</code>"), text
    )

    # 2. Qolgan hamma narsani ekranlaymiz. Shundan keyin matnda
    #    xavfli `<` qolmaydi.
    text = html.escape(text)

    # 3. Endi o'zimiz ruxsat bergan teglarni qo'yamiz.
    text = _HR.sub("──────────", text)
    text = _HEADER.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', text)
    text = _BOLD.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _BOLD_ALT.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _STRIKE.sub(lambda m: f"<s>{m.group(1)}</s>", text)
    text = _ITALIC.sub(lambda m: f"<i>{m.group(1)}</i>", text)
    text = _ITALIC_ALT.sub(lambda m: f"<i>{m.group(1)}</i>", text)
    text = _BULLET.sub(r"\1• ", text)

    # 4. Kod bloklarini joyiga qaytaramiz.
    for i, payload in enumerate(vault):
        text = text.replace(_MARK.format(i), payload)

    return text.strip()


def plain(text: str) -> str:
    """Markdown belgilarini olib tashlaydi — HTML butunlay ishlamasa."""
    text = _FENCE.sub(lambda m: m.group(2), text)
    text = _INLINE_CODE.sub(lambda m: m.group(1), text)
    text = _HEADER.sub(lambda m: m.group(1), text)
    text = _LINK.sub(lambda m: f"{m.group(1)} ({m.group(2)})", text)
    text = _BOLD.sub(lambda m: m.group(1), text)
    text = _BOLD_ALT.sub(lambda m: m.group(1), text)
    text = _STRIKE.sub(lambda m: m.group(1), text)
    return text.strip()


def split_text(text: str, limit: int = MAX_TG) -> list[str]:
    """Uzun matnni bo'laklarga bo'ladi.

    MUHIM: bo'lish HTML ga o'girishdan OLDIN qilinadi. Aks holda
    bo'linish `<b>` tegining o'rtasiga tushib, yana parse xatosi
    bo'ladi.

    Uch bosqich: paragraf → qator → majburiy kesish. Oxirgisi kerak,
    chunki model ba'zan 5000 belgilik bitta paragraf yozadi va
    eski kod uni umuman kesmasdan yuborib, xatoga uchrar edi.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for para in text.split("\n\n"):
        for piece in _fit(para, limit):
            if len(current) + len(piece) + 2 > limit:
                flush()
                current = piece
            else:
                current = f"{current}\n\n{piece}" if current else piece
    flush()
    return chunks or [text[:limit]]


def _fit(block: str, limit: int) -> list[str]:
    """Bitta blokni limitga sig'adigan bo'laklarga ajratadi."""
    if len(block) <= limit:
        return [block]

    out: list[str] = []
    current = ""
    for line in block.split("\n"):
        while len(line) > limit:  # bitta qator ham uzun bo'lishi mumkin
            if current:
                out.append(current)
                current = ""
            out.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) + 1 > limit:
            out.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        out.append(current)
    return out
