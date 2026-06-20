"""
APScheduler job definitions for the tender monitoring agent.
Orchestrates the full scrape → analyze → notify pipeline.
Loads scraper classes dynamically from sources.yaml config.
"""

from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timezone
from typing import Any, Dict, List

import structlog
import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ai.analyzer import TenderAnalyzer
from config.settings import settings
from database.operations import TenderRepository
from notifications.telegram import TelegramNotifier
from scraper.pdf_downloader import PDFDownloader

logger = structlog.get_logger(__name__)

# Global scheduler instance
scheduler: AsyncIOScheduler | None = None


def load_sources_config() -> List[Dict[str, Any]]:
    """Load tender sources from YAML configuration."""
    try:
        with open(settings.SOURCES_CONFIG_PATH, "r") as f:
            config = yaml.safe_load(f)
        sources = config.get("sources", [])
        enabled = [s for s in sources if s.get("enabled", True)]
        logger.info("Loaded tender sources", total=len(sources), enabled=len(enabled))
        return enabled
    except Exception as e:
        logger.error("Failed to load sources config", error=str(e))
        return []


def get_scraper_class(class_path: str):
    """Dynamically import a scraper class from its dotted path."""
    try:
        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except Exception as e:
        logger.error("Failed to load scraper class", class_path=class_path, error=str(e))
        return None


async def run_scrapers() -> List[Dict[str, Any]]:
    """Run all enabled scrapers and collect tenders."""
    sources = load_sources_config()
    all_tenders: List[Dict[str, Any]] = []

    for source in sources:
        scraper_class = get_scraper_class(source["scraper_class"])
        if not scraper_class:
            continue

        try:
            scraper = scraper_class(
                source_name=source["name"],
                base_url=source["base_url"],
                search_keywords=source.get("search_keywords", []),
                max_pages=source.get("max_pages", 5),
                extra=source.get("extra", {}),
            )
            # 60-second hard timeout per source
            tenders = await asyncio.wait_for(scraper.run(), timeout=60)
            all_tenders.extend(tenders)
            logger.info("Scraper completed", source=source["name"], found=len(tenders))
        except asyncio.TimeoutError:
            logger.warning("Scraper timed out (60s)", source=source["name"])
            continue
        except Exception as e:
            logger.error("Scraper failed", source=source["name"], error=str(e))
            continue

    return all_tenders


async def run_monitoring_cycle() -> Dict[str, Any]:
    """
    Execute a complete monitoring cycle:
    1. Scrape all sources
    2. Upsert to database (dedup)
    3. Analyze unanalyzed tenders with AI
    4. Download PDFs where available
    5. Notify high-scoring tenders via Telegram
    """
    cycle_start = datetime.now(timezone.utc)
    stats = {
        "started_at": cycle_start.isoformat(),
        "scraped": 0,
        "inserted": 0,
        "analyzed": 0,
        "keyword_matched": 0,
        "sent_to_ai": 0,
        "skipped_by_keyword": 0,
        "relevant_found": 0,
        "notified": 0,
        "errors": [],
    }

    logger.info("═" * 50)
    logger.info("MONITORING CYCLE STARTED", time=cycle_start.isoformat())
    logger.info("═" * 50)

    # ── Step 1: Scrape ──────────────────────────────────────────
    try:
        logger.info("Step 1/5: Running scrapers...")
        raw_tenders = await run_scrapers()
        stats["scraped"] = len(raw_tenders)
        logger.info("Scraping complete", total_found=len(raw_tenders))
    except Exception as e:
        logger.error("Scraping phase failed", error=str(e))
        stats["errors"].append(f"Scraping: {e}")
        raw_tenders = []

    # ── Step 2: Upsert to Database ──────────────────────────────
    try:
        logger.info("Step 2/5: Upserting to database...")
        inserted = await TenderRepository.bulk_upsert_tenders(raw_tenders)
        stats["inserted"] = inserted
        logger.info("Database upsert complete", inserted=inserted)
    except Exception as e:
        logger.error("Database upsert failed", error=str(e))
        stats["errors"].append(f"Database: {e}")

    # ── Step 3: Download PDFs ───────────────────────────────────
    try:
        logger.info("Step 3/5: Downloading PDFs...")
        downloader = PDFDownloader()
        unanalyzed = await TenderRepository.get_unanalyzed_tenders(limit=50)
        pdf_texts = {}

        for tender in unanalyzed:
            if tender.tender_url and tender.tender_url.endswith(".pdf"):
                pdf_path = await downloader.download(
                    tender.tender_url, tender.source, tender.tender_id
                )
                if pdf_path:
                    await TenderRepository.update_pdf_path(tender.tender_id, pdf_path)
                    text = await PDFDownloader.extract_text(pdf_path)
                    if text:
                        pdf_texts[tender.tender_id] = text

        logger.info("PDF download complete", pdfs_processed=len(pdf_texts))
    except Exception as e:
        logger.error("PDF download phase failed", error=str(e))
        stats["errors"].append(f"PDF: {e}")
        pdf_texts = {}

    # ── Step 4: AI Analysis ─────────────────────────────────────
    try:
        logger.info("Step 4/5: Running AI analysis...")
        if settings.AI_PROVIDER.lower() in ("none", "disabled", "false", ""):
            logger.info("AI analysis disabled - running in scrape-only mode")
            unanalyzed = await TenderRepository.get_unanalyzed_tenders(limit=100)
            if unanalyzed:
                for tender in unanalyzed:
                    dummy_analysis = {
                        "relevance_score": 0,
                        "is_relevant": False,
                        "key_requirements": [],
                        "emd_amount": None,
                        "eligibility_criteria": [],
                        "scope_of_work": "Scrape-only mode.",
                        "reason": "AI analysis disabled.",
                        "matched_domains": [],
                        "recommended_action": "Not Analyzed"
                    }
                    await TenderRepository.update_analysis(tender.tender_id, dummy_analysis)
                stats["analyzed"] = len(unanalyzed)
                logger.info("Tenders marked as Not Analyzed", count=len(unanalyzed))
        elif settings.GEMINI_API_KEY or settings.OPENAI_API_KEY:
            analyzer = TenderAnalyzer()
            unanalyzed = await TenderRepository.get_unanalyzed_tenders(limit=50)

            if unanalyzed:
                to_analyze = []
                keywords = [
                    "PLC", "SCADA", "Automation", "Industrial Automation", "Electrical Panel",
                    "Control Panel", "Control System", "Instrumentation", "VFD", "MCC", "PCC",
                    "LT Panel", "HT Panel", "Switchgear", "Substation", "Relay",
                    "Protection System", "Motor Control", "Electrical Works",
                    "Industrial Electrical", "Motion Platform", "Precision Engineering"
                ]

                for tender in unanalyzed:
                    text = f"{tender.title or ''} {tender.description or ''}".lower()
                    matched = any(kw.lower() in text for kw in keywords)

                    if matched:
                        logger.info("Keyword filter passed", tender_id=tender.tender_id)
                        to_analyze.append(tender)
                        stats["keyword_matched"] += 1
                    else:
                        logger.info("Keyword filter rejected", tender_id=tender.tender_id)
                        logger.info("Skipping AI analysis", tender_id=tender.tender_id)
                        dummy_analysis = {
                            "relevance_score": 0,
                            "is_relevant": False,
                            "key_requirements": [],
                            "emd_amount": None,
                            "eligibility_criteria": [],
                            "scope_of_work": "Rejected by fast keyword filter.",
                            "reason": "Did not match any mandatory keywords.",
                            "matched_domains": [],
                            "recommended_action": "Keyword Filter Rejected"
                        }
                        await TenderRepository.update_analysis(tender.tender_id, dummy_analysis)
                        stats["skipped_by_keyword"] += 1

                if to_analyze:
                    stats["sent_to_ai"] = len(to_analyze)
                    results = await analyzer.analyze_batch(to_analyze, pdf_texts)
                    for tender_id, analysis in results:
                        await TenderRepository.update_analysis(tender_id, analysis)
                    stats["analyzed"] = len(results)
                    logger.info("AI analysis complete", analyzed=len(results))
                else:
                    logger.info("No tenders passed keyword filter for AI analysis")
            else:
                logger.info("No unanalyzed tenders to process")
        else:
            logger.warning("No AI API key configured, skipping analysis")
    except Exception as e:
        logger.error("AI analysis phase failed", error=str(e))
        stats["errors"].append(f"AI: {e}")

    # ── Step 5: Notify ──────────────────────────────────────────
    try:
        logger.info("Step 5/5: Sending notifications...")
        relevant = await TenderRepository.get_unnotified_relevant(
            threshold=settings.RELEVANCE_THRESHOLD
        )
        stats["relevant_found"] = len(relevant)

        if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
            if relevant:
                notifier = TelegramNotifier()
                sent = await notifier.notify_batch(relevant)
                stats["notified"] = sent
                logger.info("Notifications sent", count=sent)
            else:
                logger.info("No new relevant tenders to notify")
        else:
            logger.warning("Telegram not configured, skipping notifications")
    except Exception as e:
        logger.error("Notification phase failed", error=str(e))
        stats["errors"].append(f"Notification: {e}")

    # ── Summary ─────────────────────────────────────────────────
    cycle_end = datetime.now(timezone.utc)
    duration = (cycle_end - cycle_start).total_seconds()
    stats["duration_seconds"] = round(duration, 1)
    stats["completed_at"] = cycle_end.isoformat()

    logger.info(
        "MONITORING CYCLE COMPLETED",
        duration=f"{duration:.1f}s",
        scraped=stats["scraped"],
        inserted=stats["inserted"],
        keyword_matched=stats.get("keyword_matched", 0),
        sent_to_ai=stats.get("sent_to_ai", 0),
        skipped_by_keyword=stats.get("skipped_by_keyword", 0),
        analyzed=stats["analyzed"],
        relevant_found=stats.get("relevant_found", 0),
        notified=stats["notified"],
        errors=len(stats["errors"]),
    )
    logger.info("═" * 50)

    return stats


async def poll_telegram_commands() -> None:
    """Poll Telegram for incoming bot commands."""
    if settings.TELEGRAM_BOT_TOKEN:
        notifier = TelegramNotifier()
        await notifier.poll_updates()


def setup_scheduler() -> AsyncIOScheduler:
    """Configure and return the APScheduler instance."""
    global scheduler

    scheduler = AsyncIOScheduler(
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 3600,
        }
    )

    # Main monitoring cycle — every N hours
    scheduler.add_job(
        run_monitoring_cycle,
        trigger=IntervalTrigger(hours=settings.SCRAPE_INTERVAL_HOURS),
        id="monitoring_cycle",
        name="Tender Monitoring Cycle",
        replace_existing=True,
    )

    # Telegram command polling — every 30 seconds
    scheduler.add_job(
        poll_telegram_commands,
        trigger=IntervalTrigger(seconds=30),
        id="telegram_poll",
        name="Telegram Command Poll",
        replace_existing=True,
    )

    # Cleanup old tenders — daily
    scheduler.add_job(
        lambda: asyncio.ensure_future(TenderRepository.delete_old_tenders(90)),
        trigger=IntervalTrigger(days=1),
        id="cleanup_old",
        name="Cleanup Old Tenders",
        replace_existing=True,
    )

    logger.info(
        "Scheduler configured",
        interval_hours=settings.SCRAPE_INTERVAL_HOURS,
        jobs=len(scheduler.get_jobs()) if scheduler.get_jobs() else 0,
    )

    return scheduler
