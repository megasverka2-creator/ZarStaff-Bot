"""Sozlamalar."""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

LOCAL_SQLITE = "sqlite+aiosqlite:///zarstaff.db"


def _env(name: str) -> str | None:
    v = os.getenv(name)
    if v is None:
        return None
    v = v.strip()
    return v or None


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
        if problems:
            raise RuntimeError(
                "Sozlamalarda xato:\n\n" + "\n\n".join(f" • {p}" for p in problems)
            )


settings = Settings()
