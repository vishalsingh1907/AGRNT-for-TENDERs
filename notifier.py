"""
Telegram notifier — sends ONE consolidated message with all relevant tenders.
No spam. No bot commands. Just one clean message.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx

from config import settings

logger = logging.getLogger(__name__)

# Telegram max message length
MAX_MESSAGE_LENGTH = 4096


async def send_telegram_message(text: str, parse_mode: str = "HTML") -> bool:
    """Send a single message to Telegram."""
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID

    if not token or not chat_id:
        logger.error("Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload)
            if response.status_code == 200:
                logger.info("Telegram message sent successfully")
                return True
            else:
                logger.error(f"Telegram send failed: {response.status_code} — {response.text}")
                return False
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False


def format_tender(tender: Dict[str, Any], index: int) -> str:
    """Format a single tender for display."""
    title = tender.get("title", "N/A")[:150]
    org = tender.get("organization", "N/A")[:80]
    closing = tender.get("closing_date", "N/A")
    source = tender.get("source", "N/A")
    url = tender.get("url", "")
    keywords = ", ".join(tender.get("matched_keywords", [])[:5])
    score = tender.get("relevance_score", 0)

    link_text = url if url else "No link"

    return (
        f"{'─' * 32}\n"
        f"<b>{index}.</b> {title}\n"
        f"🏢 {org}\n"
        f"⏰ Closing: <b>{closing}</b>\n"
        f"📌 Source: {source}\n"
        f"🔑 Keywords [{score}]: {keywords}\n"
        f"🔗 {link_text}\n"
    )


async def notify_relevant_tenders(tenders: List[Dict[str, Any]], stats: Dict[str, Any]) -> bool:
    """
    Send ONE Telegram message with all relevant tenders.
    If no relevant tenders, sends a short status update.
    """
    if not tenders:
        # Short status — no spam
        msg = (
            "📊 <b>Tender Scan Complete</b>\n\n"
            f"🔍 Websites scraped: {stats.get('sites_scraped', 0)}\n"
            f"📄 Total tenders found: {stats.get('total_scraped', 0)}\n"
            f"❌ No NEW relevant tenders for Kapoor Engineers found.\n\n"
            f"⏱ Duration: {stats.get('duration', 'N/A')}s\n"
            f"⚠️ Errors: {stats.get('errors', 0)}"
        )
        return await send_telegram_message(msg)

    # Build the consolidated message
    cycle = stats.get('cycle', 1)
    header = (
        f"🚨 <b>NEW TENDER ALERT — Kapoor Engineers</b> (Cycle {cycle})\n"
        f"📅 {stats.get('date', 'Today')}\n\n"
        f"🔍 Scraped {stats.get('sites_scraped', 0)} websites\n"
        f"📄 Total found: {stats.get('total_scraped', 0)}\n"
        f"✅ <b>NEW Relevant: {len(tenders)}</b>\n"
    )

    body_parts = []
    for i, tender in enumerate(tenders, 1):
        body_parts.append(format_tender(tender, i))

    footer = (
        f"\n{'═' * 32}\n"
        f"⏱ Scan duration: {stats.get('duration', 'N/A')}s\n"
        f"🤖 kapoorengineers.in continuous bot"
    )

    full_message = header + "\n".join(body_parts) + footer

    # If message is too long, split into multiple messages
    if len(full_message) <= MAX_MESSAGE_LENGTH:
        return await send_telegram_message(full_message)
    else:
        # Send header + first batch
        messages_sent = True
        current_msg = header
        batch_count = 0

        for i, tender in enumerate(tenders, 1):
            tender_text = format_tender(tender, i)
            if len(current_msg) + len(tender_text) + len(footer) > MAX_MESSAGE_LENGTH:
                # Send current batch
                batch_count += 1
                success = await send_telegram_message(current_msg + f"\n(Part {batch_count})")
                messages_sent = messages_sent and success
                current_msg = f"📋 <b>Continued (Part {batch_count + 1})</b>\n"

            current_msg += tender_text

        # Send last batch with footer
        current_msg += footer
        success = await send_telegram_message(current_msg)
        messages_sent = messages_sent and success

        return messages_sent
