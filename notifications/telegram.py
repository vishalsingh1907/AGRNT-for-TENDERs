"""
Telegram notification sender and bot command handler.
Uses httpx for async HTTP calls to the Telegram Bot API.
Supports HTML formatting and bot commands.
"""

from __future__ import annotations

import asyncio
import html
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import structlog

from config.settings import settings
from database.operations import TenderRepository

logger = structlog.get_logger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}"
MAX_MESSAGE_LENGTH = 4096
RATE_LIMIT_DELAY = 3  # seconds between messages (Telegram allows ~30/sec, we go slow)


class TelegramNotifier:
    """Sends tender notifications and handles bot commands via Telegram."""

    def __init__(self):
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.api_base = TELEGRAM_API.format(token=self.token)
        self._last_update_id = 0

    def _esc(self, text: str) -> str:
        """Escape HTML special characters for Telegram."""
        return html.escape(str(text)) if text else ""

    def _format_tender_message(self, tender) -> str:
        """Format a tender into an HTML Telegram message."""
        # Extract AI analysis data
        analysis = tender.ai_analysis or {}
        summary = analysis.get("summary", "No summary available")
        emd = analysis.get("emd_amount", "Not specified")
        recommendation = analysis.get("recommendation", "N/A")
        matched = analysis.get("matched_keywords", [])

        score = tender.ai_score or 0
        score_bar = self._score_bar(score)

        # Format closing date
        closing = "N/A"
        if tender.closing_date:
            closing = tender.closing_date.strftime("%d %b %Y, %I:%M %p")

        msg = (
            f"🏗️ <b>New Relevant Tender Found!</b>\n\n"
            f"📋 <b>Title:</b> {self._esc(tender.title)}\n"
            f"🏢 <b>Organization:</b> {self._esc(tender.organization)}\n"
            f"📅 <b>Closing Date:</b> {self._esc(closing)}\n"
            f"🎯 <b>AI Score:</b> {score}/100 {score_bar}\n"
            f"💡 <b>Recommendation:</b> {self._esc(recommendation)}\n"
            f"💰 <b>EMD:</b> {self._esc(emd or 'Not specified')}\n\n"
            f"📝 <b>AI Summary:</b>\n{self._esc(summary)}\n\n"
        )

        if matched:
            msg += f"🔑 <b>Matched Keywords:</b> {self._esc(', '.join(matched[:10]))}\n\n"

        if tender.tender_url:
            msg += f"🔗 <a href='{tender.tender_url}'>View Tender Details</a>\n"

        msg += f"\n📌 <i>Source: {self._esc(tender.source)} | ID: {self._esc(tender.tender_id)}</i>"

        return msg

    def _score_bar(self, score: int) -> str:
        """Generate a visual score bar."""
        filled = score // 10
        empty = 10 - filled
        if score >= 80:
            return "🟩" * filled + "⬜" * empty
        elif score >= 50:
            return "🟨" * filled + "⬜" * empty
        else:
            return "🟥" * filled + "⬜" * empty

    async def send_message(self, text: str, chat_id: str | None = None) -> bool:
        """Send a message via Telegram Bot API."""
        if not self.token:
            logger.warning("Telegram bot token not configured")
            return False

        target_chat = chat_id or self.chat_id
        if not target_chat:
            logger.warning("Telegram chat ID not configured")
            return False

        # Truncate if too long
        if len(text) > MAX_MESSAGE_LENGTH:
            text = text[: MAX_MESSAGE_LENGTH - 100] + "\n\n<i>... message truncated</i>"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.api_base}/sendMessage",
                    json={
                        "chat_id": target_chat,
                        "text": text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": False,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                if not data.get("ok"):
                    logger.error("Telegram API error", response=data)
                    return False
                return True

        except Exception as e:
            logger.error("Failed to send Telegram message", error=str(e))
            return False

    async def notify_tender(self, tender) -> bool:
        """Send a notification for a single tender."""
        msg = self._format_tender_message(tender)
        success = await self.send_message(msg)
        if success:
            logger.info("Telegram notification sent", tender_id=tender.tender_id)
        return success

    async def notify_batch(self, tenders: list) -> int:
        """Send notifications for multiple tenders. Returns count of successful sends."""
        sent = 0
        for tender in tenders:
            success = await self.notify_tender(tender)
            if success:
                sent += 1
                await TenderRepository.mark_notified(tender.tender_id)
            await asyncio.sleep(RATE_LIMIT_DELAY)
        logger.info("Batch notifications complete", total=len(tenders), sent=sent)
        return sent

    # ── Bot Command Handlers ───────────────────────────────────

    async def handle_command(self, command: str, args: str = "", chat_id: str = "") -> None:
        """Route and handle a Telegram bot command."""
        target = chat_id or self.chat_id
        handlers = {
            "/latest": self._cmd_latest,
            "/today": self._cmd_today,
            "/search": self._cmd_search,
            "/stats": self._cmd_stats,
            "/help": self._cmd_help,
        }

        handler = handlers.get(command)
        if handler:
            await handler(args, target)
        else:
            await self.send_message("❓ Unknown command. Use /help to see available commands.", target)

    async def _cmd_latest(self, args: str, chat_id: str) -> None:
        """Handle /latest — show most recent tenders."""
        tenders = await TenderRepository.get_latest_tenders(limit=5)
        if not tenders:
            await self.send_message("📭 No tenders found in the database.", chat_id)
            return

        msg = "📋 <b>Latest Tenders</b>\n\n"
        for i, t in enumerate(tenders, 1):
            score = t.ai_score or "N/A"
            closing = t.closing_date.strftime("%d %b %Y") if t.closing_date else "N/A"
            msg += (
                f"<b>{i}.</b> {self._esc(t.title[:100])}\n"
                f"   🏢 {self._esc(t.organization or 'N/A')} | 🎯 Score: {score}\n"
                f"   📅 Closing: {closing}\n"
                f"   🔗 <a href='{t.tender_url}'>View</a>\n\n"
            )

        await self.send_message(msg, chat_id)

    async def _cmd_today(self, args: str, chat_id: str) -> None:
        """Handle /today — show tenders added today."""
        tenders = await TenderRepository.get_today_tenders()
        if not tenders:
            await self.send_message("📭 No tenders added today yet.", chat_id)
            return

        msg = f"📅 <b>Today's Tenders ({len(tenders)} found)</b>\n\n"
        for i, t in enumerate(tenders[:10], 1):
            score = t.ai_score or "N/A"
            msg += (
                f"<b>{i}.</b> {self._esc(t.title[:100])}\n"
                f"   🏢 {self._esc(t.organization or 'N/A')} | 🎯 Score: {score}\n\n"
            )

        if len(tenders) > 10:
            msg += f"<i>... and {len(tenders) - 10} more</i>"

        await self.send_message(msg, chat_id)

    async def _cmd_search(self, args: str, chat_id: str) -> None:
        """Handle /search <keyword> — search tenders by keyword."""
        keyword = args.strip()
        if not keyword:
            await self.send_message("Usage: /search &lt;keyword&gt;\nExample: /search SCADA", chat_id)
            return

        tenders = await TenderRepository.search_tenders(keyword, limit=10)
        if not tenders:
            await self.send_message(f"🔍 No tenders found for '{self._esc(keyword)}'.", chat_id)
            return

        msg = f"🔍 <b>Search Results for '{self._esc(keyword)}'</b>\n\n"
        for i, t in enumerate(tenders, 1):
            score = t.ai_score or "N/A"
            msg += (
                f"<b>{i}.</b> {self._esc(t.title[:100])}\n"
                f"   🏢 {self._esc(t.organization or 'N/A')} | 🎯 Score: {score}\n"
                f"   🔗 <a href='{t.tender_url}'>View</a>\n\n"
            )

        await self.send_message(msg, chat_id)

    async def _cmd_stats(self, args: str, chat_id: str) -> None:
        """Handle /stats — show database statistics."""
        stats = await TenderRepository.get_stats()
        dist = stats.get("score_distribution", {})

        msg = (
            "📊 <b>Tender Agent Statistics</b>\n\n"
            f"📁 <b>Total Tenders:</b> {stats['total_tenders']}\n"
            f"📅 <b>Added Today:</b> {stats['today_count']}\n"
            f"🤖 <b>Analyzed:</b> {stats['analyzed']}\n"
            f"⏳ <b>Pending Analysis:</b> {stats['unanalyzed']}\n"
            f"✅ <b>Relevant (Score ≥75):</b> {stats['relevant']}\n"
            f"📨 <b>Notified:</b> {stats['notified']}\n"
            f"📈 <b>Average Score:</b> {stats['average_score']}\n"
            f"⚠️ <b>Closing Soon (7 days):</b> {stats['closing_soon']}\n\n"
            f"<b>Score Distribution:</b>\n"
            f"  🟥 0-24:   {dist.get('0-24', 0)}\n"
            f"  🟨 25-50:  {dist.get('25-50', 0)}\n"
            f"  🟩 51-75:  {dist.get('51-75', 0)}\n"
            f"  🌟 76-100: {dist.get('76-100', 0)}\n\n"
            f"<b>By Source:</b>\n"
        )
        for source, count in stats.get("by_source", {}).items():
            msg += f"  📌 {self._esc(source)}: {count}\n"

        await self.send_message(msg, chat_id)

    async def _cmd_help(self, args: str, chat_id: str) -> None:
        """Handle /help — show available commands."""
        msg = (
            "🤖 <b>Tender Agent Bot Commands</b>\n\n"
            "/latest — Show 5 most recent tenders\n"
            "/today — Show tenders added today\n"
            "/search &lt;keyword&gt; — Search tenders\n"
            "/stats — Show statistics\n"
            "/help — Show this help message\n"
        )
        await self.send_message(msg, chat_id)

    # ── Polling for Bot Commands ────────────────────────────────

    async def poll_updates(self) -> None:
        """Poll Telegram for incoming bot commands (non-blocking single check)."""
        if not self.token:
            return

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.api_base}/getUpdates",
                    params={"offset": self._last_update_id + 1, "timeout": 5},
                )
                data = resp.json()

            if not data.get("ok"):
                return

            for update in data.get("result", []):
                self._last_update_id = update["update_id"]
                message = update.get("message", {})
                text = message.get("text", "").strip()
                chat_id = str(message.get("chat", {}).get("id", ""))

                if text.startswith("/"):
                    parts = text.split(maxsplit=1)
                    command = parts[0].lower()
                    args = parts[1] if len(parts) > 1 else ""
                    await self.handle_command(command, args, chat_id)

        except Exception as e:
            logger.debug("Telegram poll error", error=str(e))
