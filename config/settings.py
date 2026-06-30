"""
Minimal settings — loads credentials from .env file.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── AI (OpenRouter — optional, for future use) ───────────
AI_API_KEY = os.getenv("API_KEY_OF_MODEL", "") or os.getenv("OPENAI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "meta-llama/llama-3.3-70b-instruct:free")

# ── Scraping ──────────────────────────────────────────────
SCRAPE_TIMEOUT = int(os.getenv("SCRAPE_TIMEOUT_MS", "60000")) // 1000  # seconds
REQUEST_TIMEOUT = 30  # seconds for httpx requests
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# ── Tender Freshness ─────────────────────────────────────
# Only show tenders closing within this many days from now
CLOSING_WITHIN_DAYS = 30
# Only show tenders published within this many days
PUBLISHED_WITHIN_DAYS = 7

# ── Logging ───────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
