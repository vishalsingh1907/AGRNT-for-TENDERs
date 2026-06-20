"""
Application settings loaded from environment variables.
All secrets and configuration are managed here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ───────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///tender_agent.db",
        description="Async SQLite connection string",
    )
    DATABASE_URL_SYNC: str = Field(
        default="sqlite:///tender_agent.db",
        description="Sync SQLite URL for APScheduler job store",
    )

    # ── AI Provider ────────────────────────────────────────────
    AI_PROVIDER: str = Field(default="gemini", description="gemini or openai")
    GEMINI_API_KEY: str = Field(default="", description="Google Gemini API key")
    OPENAI_API_KEY: str = Field(default="", description="OpenAI API key (fallback)")
    AI_MODEL: str = Field(default="gemini-2.5-flash", description="Model name")
    AI_MAX_RPM: int = Field(default=10, description="Max AI requests per minute")

    # ── Telegram ───────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = Field(default="", description="Telegram Bot API token")
    TELEGRAM_CHAT_ID: str = Field(default="", description="Telegram chat/group ID")

    # ── Scraping ───────────────────────────────────────────────
    SCRAPE_INTERVAL_HOURS: int = Field(default=6, description="Scrape interval in hours")
    SCRAPE_TIMEOUT_MS: int = Field(default=60000, description="Page load timeout in ms")
    SCRAPE_DELAY_MIN: float = Field(default=2.0, description="Min delay between pages (sec)")
    SCRAPE_DELAY_MAX: float = Field(default=5.0, description="Max delay between pages (sec)")
    MAX_PAGES_PER_SOURCE: int = Field(default=10, description="Max pages to scrape per source")
    MAX_PAGES_CPPP: int = Field(default=3, description="Max pages to scrape from CPPP specifically")

    # ── Relevance ──────────────────────────────────────────────
    RELEVANCE_THRESHOLD: int = Field(default=30, description="Min score for notification")

    # ── Paths ──────────────────────────────────────────────────
    PDF_DOWNLOAD_DIR: str = Field(default="./downloads", description="PDF download directory")
    SOURCES_CONFIG_PATH: str = Field(default="./config/sources.yaml", description="Tender sources YAML")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    # ── Dashboard ──────────────────────────────────────────────
    DASHBOARD_HOST: str = Field(default="0.0.0.0", description="Dashboard bind host")
    DASHBOARD_PORT: int = Field(default=8000, description="Dashboard port")

    @property
    def pdf_dir(self) -> Path:
        path = Path(self.PDF_DOWNLOAD_DIR)
        path.mkdir(parents=True, exist_ok=True)
        return path


# ── Business Profile (used for AI relevance scoring) ────────────

COMPANY_PROFILE = """
Kapoor Engineers Pvt. Ltd.

Domains:
- PLC Systems
- SCADA Systems
- Industrial Automation
- Electrical Panels
- Instrumentation
- Control Systems
- Switchgear
- Substations
- Industrial Electronics
- Electrical Engineering Projects
"""

RELEVANT_KEYWORDS: List[str] = [
    "PLC", "SCADA", "Automation", "Electrical Panel",
    "Instrumentation", "Control System", "Switchgear",
    "Substation", "Industrial Electronics", "Electrical Engineering",
    "MCC", "PCC", "VFD", "Relay Panel", "Control Panel", "APFC"
]


# Singleton instance
settings = Settings()
