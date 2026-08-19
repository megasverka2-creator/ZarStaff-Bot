"""Sozlamalar."""
import os
from dataclasses import dataclass, field
from datetime import timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

LOCAL_SQLITE = "sqlite+aiosqlite:///zarstaff.db"

# O'zbekiston vaqti. Kunlik limit va hisobot shu bo'yicha hisoblanadi -
# UTC ishlatsak limit mahalliy soat 05:00 da yangilanadi, yarim tunda emas.
UZ_OFFSET_HOURS = 5


def _env(name: str) -> str | None:
    v = os.getenv(name)
    if v is None:
        return None
    v = v.strip()
    return v or None


def _int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    return [int(p) for p in raw.replace(" ", "").split(",") if p.lstrip("-").isdigit()]


def _normalize_db_url(raw: str | None) -> str:
    if raw is None:
        return LOCAL_SQLITE
    if raw.startswith("postgresql+"):
        return raw
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    if raw.startswith("postgres://"):
        return raw.replace("postgres://", "postgresql+asyncpg://", 1)
    return raw


@dataclass(frozen=True)
class Settings:
    bot_token: str | None = _env("STAFF_BOT_TOKEN")
    anthropic_key: str | None = _env("ANTHROPIC_API_KEY")

    # Kim ishlata oladi. Bo'sh bo'lsa - hech kim.
    allowed_users: list[int] = field(
        default_factory=lambda: _ids(_env("ALLOWED_USERS"))
    )
    # Qaysi guruhlarda ishlaydi. Bo'sh bo'lsa - hamma joyda
    # (faqat allowed_users uchun).
    allowed_chats: list[int] = field(
        default_factory=lambda: _ids(_env("ALLOWED_CHATS"))
    )

    database_url: str = _normalize_db_url(_env("DATABASE_URL"))

    # Taksi botining bazasi - FAQAT O'QISH uchun.
    taxi_database_url: str | None = field(
        default_factory=lambda: (
            _normalize_db_url(_env("TAXI_DATABASE_URL"))
            if _env("TAXI_DATABASE_URL")
            else None
        )
    )

    # Xarajat cheklovi
    daily_limit_usd: float = float(_env("DAILY_LIMIT_USD") or 5.0)
    # Guruh xotirasi: nechta oxirgi xabar kontekstga qo'shiladi
    memory_messages: int = int(_env("MEMORY_MESSAGES") or 25)

    # Mahalliy vaqt siljishi, soat. Kunlik limit shu bo'yicha yangilanadi.
    tz_offset_hours: int = _int("TZ_OFFSET_HOURS", UZ_OFFSET_HOURS)

    # Javob yozilishi bilan ko'rsatilsinmi (oqim rejimi).
    # O'chirish uchun STREAM=0.
    stream: bool = field(
        default_factory=lambda: (_env("STREAM") or "1") not in ("0", "false", "no")
    )

    # ---- Avtomatik kunlik hisobot ----
    # Qaysi soatda yuboriladi (mahalliy vaqt). Manfiy son - o'chirilgan.
    report_hour: int = _int("REPORT_HOUR", -1)
    # Qaysi chatga. Bo'sh bo'lsa - allowed_chats dagi birinchisi.
    report_chat_id: int = _int("REPORT_CHAT_ID", 0)

    # ---- Ovozli xabar ----
    # Whisper bilan mos keladigan transkripsiya xizmati. Bo'sh bo'lsa
    # ovozli xabar qabul qilinmaydi (Anthropic audio tushunmaydi).
    voice_api_url: str | None = field(
        default_factory=lambda: _env("VOICE_API_URL")
    )
    voice_api_key: str | None = field(
        default_factory=lambda: _env("VOICE_API_KEY")
    )
    voice_model: str = field(
        default_factory=lambda: _env("VOICE_MODEL") or "whisper-1"
    )

    @property
    def tz(self) -> timezone:
        return timezone(timedelta(hours=self.tz_offset_hours))

    @property
    def report_enabled(self) -> bool:
        return 0 <= self.report_hour <= 23

    @property
    def voice_enabled(self) -> bool:
        return bool(self.voice_api_url and self.voice_api_key)

    def report_target(self) -> int | None:
        if not self.report_enabled:
            return None
        if self.report_chat_id:
            return self.report_chat_id
        return self.allowed_chats[0] if self.allowed_chats else None

    def validate(self) -> None:
        problems = []
        if not self.bot_token:
            problems.append("STAFF_BOT_TOKEN bo'sh.")
        if not self.anthropic_key:
            problems.append("ANTHROPIC_API_KEY bo'sh.")
        if not self.allowed_users:
            problems.append(
                "ALLOWED_USERS bo'sh. Bu bot pul sarflaydi - kim "
                "ishlatishi mumkinligini ko'rsatish SHART."
            )
        if os.getenv("DATABASE_URL") is not None and _env("DATABASE_URL") is None:
            problems.append("DATABASE_URL bor, lekin BO'SH.")
        if self.report_enabled and self.report_target() is None:
            problems.append(
                "REPORT_HOUR qo'yilgan, lekin hisobot qaysi chatga "
                "borishi noma'lum. REPORT_CHAT_ID yoki ALLOWED_CHATS ni "
                "to'ldiring."
            )
        if problems:
            raise RuntimeError(
                "Sozlamalarda xato:\n\n" + "\n\n".join(f" • {p}" for p in problems)
            )


settings = Settings()
