"""
Tender Monitoring Agent - Main Entry Point

Runs continuously: Scrape -> Keyword Match -> Telegram (new tenders only) -> Sleep 30 min -> Repeat.

Tracks already-seen tenders in a simple JSON file so you never get duplicate alerts.

Usage:
    python main.py              # Run continuously (every 30 min)
    python main.py --once       # Run once and exit
    python main.py --interval 15  # Custom interval in minutes
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import structlog

# ── Logging ──────────────────────────────────────────────
def configure_logging():
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

configure_logging()
logger = structlog.get_logger(__name__)


# ── Seen Tenders Tracker ─────────────────────────────────
SEEN_FILE = Path(__file__).parent / "seen_tenders.json"


def _tender_hash(tender: Dict[str, Any]) -> str:
    """Create a unique hash for a tender based on title + source."""
    raw = f"{tender.get('title', '')[:100].lower().strip()}|{tender.get('source', '')}"
    return hashlib.md5(raw.encode()).hexdigest()


def load_seen() -> set:
    """Load the set of already-seen tender hashes."""
    if SEEN_FILE.exists():
        try:
            data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
            return set(data.get("hashes", []))
        except Exception:
            return set()
    return set()


def save_seen(seen: set):
    """Save the seen tender hashes to disk."""
    # Keep only last 5000 hashes to prevent file from growing forever
    hashes = list(seen)[-5000:]
    SEEN_FILE.write_text(
        json.dumps({"hashes": hashes, "updated": datetime.now().isoformat()}, indent=2),
        encoding="utf-8",
    )


def filter_new_tenders(tenders: List[Dict[str, Any]], seen: set) -> List[Dict[str, Any]]:
    """Return only tenders we haven't seen before."""
    new = []
    for t in tenders:
        h = _tender_hash(t)
        if h not in seen:
            new.append(t)
            seen.add(h)
    return new


# ── Scrapers ─────────────────────────────────────────────
async def run_all_scrapers():
    """Run all 7 scrapers and collect tenders."""
    from scrapers.hal_eproc import HALEprocScraper
    from scrapers.dmrc import DMRCScraper
    from scrapers.hal_tenders import HALTendersScraper
    from scrapers.eprocure import EProcureScraper
    from scrapers.bidassist import BidAssistScraper
    from scrapers.tenderdetail import TenderDetailScraper
    from scrapers.defproc import DefProcScraper

    scrapers = [
        EProcureScraper(),      # Govt eProcure -- httpx (fast)
        DefProcScraper(),       # Defence Procurement -- httpx (fast)
        HALEprocScraper(),      # HAL eProcurement -- Playwright
        HALTendersScraper(),    # HAL India -- Playwright
        DMRCScraper(),          # Delhi Metro -- Playwright
        BidAssistScraper(),     # BidAssist -- Playwright
        TenderDetailScraper(),  # TenderDetail -- Playwright
    ]

    all_tenders = []
    sites_scraped = 0
    errors = 0

    for scraper in scrapers:
        logger.info(f"Scraping: {scraper.SOURCE_NAME}",
                    url=scraper.BASE_URL)
        try:
            tenders = await scraper.scrape()
            all_tenders.extend(tenders)
            sites_scraped += 1
            logger.info(f"[OK] {scraper.SOURCE_NAME}: {len(tenders)} tenders found")
        except Exception as e:
            errors += 1
            logger.error(f"[FAIL] {scraper.SOURCE_NAME} FAILED", error=str(e))

    return all_tenders, sites_scraped, errors


# ── Single Scan Cycle ────────────────────────────────────
async def run_cycle(cycle_num: int = 1):
    """Run one complete scan cycle. Returns True if new tenders were found."""
    from analyzer import analyze_relevance
    from notifier import notify_relevant_tenders

    logger.info("=" * 60)
    logger.info(f"SCAN CYCLE #{cycle_num}")
    logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    start_time = time.time()

    # Step 1: Scrape
    logger.info("STEP 1: Scraping all tender websites...")
    all_tenders, sites_scraped, errors = await run_all_scrapers()
    logger.info(f"Scraping complete: {len(all_tenders)} tenders from {sites_scraped} sites")

    # Step 2: Analyze relevance
    logger.info("STEP 2: Analyzing relevance...")
    relevant_tenders = analyze_relevance(all_tenders)
    logger.info(f"Relevant tenders: {len(relevant_tenders)} out of {len(all_tenders)}")

    # Step 3: Filter out already-seen tenders
    logger.info("STEP 3: Filtering new tenders...")
    seen = load_seen()
    new_tenders = filter_new_tenders(relevant_tenders, seen)
    save_seen(seen)
    logger.info(f"NEW tenders: {len(new_tenders)} (already seen: {len(relevant_tenders) - len(new_tenders)})")

    # Step 4: Send Telegram only if there are NEW relevant tenders
    duration = round(time.time() - start_time, 1)
    stats = {
        "sites_scraped": sites_scraped,
        "total_scraped": len(all_tenders),
        "relevant": len(relevant_tenders),
        "new": len(new_tenders),
        "errors": errors,
        "duration": duration,
        "date": datetime.now().strftime("%d-%m-%Y %H:%M"),
        "cycle": cycle_num,
    }

    logger.info("STEP 4: Sending Telegram status update...")
    success = await notify_relevant_tenders(new_tenders, stats)
    if success:
        logger.info("[OK] Telegram notification sent!")
    else:
        logger.error("[FAIL] Failed to send Telegram notification")

    logger.info("-" * 60)
    logger.info("CYCLE COMPLETE", **stats)
    logger.info("-" * 60)

    return len(new_tenders) > 0


# ── Main Loop ────────────────────────────────────────────
async def main():
    """Run the monitoring agent continuously."""
    import argparse

    parser = argparse.ArgumentParser(description="Kapoor Engineers Tender Monitor")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=int, default=30, help="Scan interval in minutes (default: 30)")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("KAPOOR ENGINEERS - TENDER MONITORING AGENT")
    logger.info("=" * 60)

    if args.once:
        logger.info("Mode: Single scan (--once)")
        await run_cycle(1)
        return

    interval_sec = args.interval * 60
    logger.info(f"Mode: Continuous monitoring every {args.interval} minutes")
    logger.info(f"Press Ctrl+C to stop")
    logger.info("=" * 60)

    cycle = 0
    while True:
        cycle += 1
        try:
            await run_cycle(cycle)
        except Exception as e:
            logger.error(f"Cycle {cycle} crashed (will retry next cycle)", error=str(e))

        # Sleep until next cycle
        next_run = datetime.now().strftime("%H:%M")
        wake_time = datetime.fromtimestamp(time.time() + interval_sec).strftime("%H:%M")
        logger.info(f"Sleeping {args.interval} min... Next scan at {wake_time}")

        try:
            await asyncio.sleep(interval_sec)
        except asyncio.CancelledError:
            logger.info("Shutting down gracefully...")
            break


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAgent stopped by user.")
