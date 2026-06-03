from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    excel_path: Path
    responsible_default: str
    check_interval_minutes: int
    session_dir: Path
    orders_url: str
    headless: bool
    default_tipo: str
    browser_channel: str | None
    cdp_url: str | None
    browser_executable: str | None


def _bool_from_env(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "sim", "y"}


def load_settings(env_file: str | os.PathLike[str] | None = None) -> Settings:
    """Load application settings from .env and environment variables."""

    load_dotenv(env_file)

    excel_path = Path(os.getenv("EXCEL_PATH", "./data/pedidos_aliexpress.xlsx")).expanduser()
    session_dir = Path(os.getenv("ALIEXPRESS_SESSION_DIR", "./browser-session")).expanduser()
    interval_raw = os.getenv("CHECK_INTERVAL_MINUTES", "60")

    try:
        interval = max(1, int(interval_raw))
    except ValueError as exc:
        raise ValueError("CHECK_INTERVAL_MINUTES deve ser um numero inteiro positivo.") from exc

    default_tipo = _normalize_tipo(os.getenv("DEFAULT_TIPO", "Entrada"))

    return Settings(
        excel_path=excel_path,
        responsible_default=os.getenv("RESPONSAVEL_PADRAO", "Nao informado").strip(),
        check_interval_minutes=interval,
        session_dir=session_dir,
        orders_url=os.getenv(
            "ALIEXPRESS_ORDERS_URL",
            "https://www.aliexpress.com/p/order/index.html",
        ).strip(),
        headless=_bool_from_env(os.getenv("HEADLESS"), False),
        default_tipo=default_tipo,
        browser_channel=os.getenv("BROWSER_CHANNEL", "chrome").strip() or None,
        cdp_url=os.getenv("CDP_URL", "").strip() or None,
        browser_executable=os.getenv("BROWSER_EXECUTABLE", "").strip() or None,
    )


def _normalize_tipo(value: str | None) -> str:
    normalized = str(value or "Entrada").strip().lower()
    if normalized == "entrada":
        return "Entrada"
    if normalized in {"saida", "saída"}:
        return "Saída"
    raise ValueError('DEFAULT_TIPO deve ser "Entrada" ou "Saida".')
