"""
Tender Monitoring Agent — Main Entry Point

Starts the FastAPI dashboard, APScheduler, and Telegram bot polling.
Supports:
  --run-now    Run an immediate monitoring cycle before starting the scheduler
  --port PORT  Override the dashboard port (default: 8000)
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import logging

import structlog
import uvicorn

from config.settings import settings
from dashboard.app import create_app, set_last_cycle_stats
from database.connection import close_db, init_db
from scheduler.jobs import run_monitoring_cycle, setup_scheduler


def configure_logging() -> None:
    """Configure structured logging for the application."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.LOG_LEVEL.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


logger = structlog.get_logger(__name__)


async def run_initial_cycle() -> None:
    """Run an immediate monitoring cycle."""
    logger.info("Running initial monitoring cycle (--run-now)")
    try:
        stats = await run_monitoring_cycle()
        set_last_cycle_stats(stats)
    except Exception as e:
        logger.error("Initial cycle failed", error=str(e))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Tender Monitoring Agent")
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Run an immediate monitoring cycle before starting the scheduler",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=settings.DASHBOARD_PORT,
        help=f"Dashboard port (default: {settings.DASHBOARD_PORT})",
    )
    return parser.parse_args()


async def startup(run_now: bool = False) -> None:
    """Application startup sequence."""
    logger.info("=" * 60)
    logger.info("🏗️  TENDER MONITORING AGENT STARTING")
    logger.info("=" * 60)
    
    # ── Startup Validation ───────────────────────────────────────
    if settings.AI_PROVIDER.lower() == "gemini":
        placeholders = {
            "",
            "changeme",
            "placeholder",
            "your_gemini_api_key_here"
        }
        if settings.GEMINI_API_KEY.lower().strip() in placeholders:
            logger.error(
                "❌ CRITICAL ERROR: Invalid or missing GEMINI_API_KEY. "
                "Please update your .env file with a real API key from https://aistudio.google.com/apikey"
            )
            sys.exit(1)
        logger.info("Gemini API key detected: YES")
    elif settings.AI_PROVIDER.lower() in ("none", "disabled", "false", ""):
        logger.info("AI analysis disabled - running in scrape-only mode")
    
    logger.info(f"AI Provider: {settings.AI_PROVIDER.lower()}")
    logger.info(f"AI Model: {settings.AI_MODEL}")
    logger.info(f"Scrape Interval: {settings.SCRAPE_INTERVAL_HOURS} hours")
    logger.info(
        "Notification threshold",
        threshold=settings.RELEVANCE_THRESHOLD
    )
    logger.info("-" * 60)

    # Initialize database
    await init_db()

    # Run immediate cycle if requested
    if run_now:
        await run_initial_cycle()

    # Setup and start scheduler
    sched = setup_scheduler()
    sched.start()
    logger.info("Scheduler started", jobs=len(sched.get_jobs()))


async def shutdown() -> None:
    """Application shutdown sequence."""
    logger.info("Shutting down...")
    await close_db()
    logger.info("Shutdown complete")


def main() -> None:
    """Main entry point."""
    args = parse_args()
    configure_logging()

    # Create FastAPI app
    app = create_app()

    @app.on_event("startup")
    async def on_startup():
        await startup(run_now=args.run_now)

    @app.on_event("shutdown")
    async def on_shutdown():
        await shutdown()

    # Run the server
    logger.info("Starting dashboard", host=settings.DASHBOARD_HOST, port=args.port)
    uvicorn.run(
        app,
        host=settings.DASHBOARD_HOST,
        port=args.port,
        log_level=settings.LOG_LEVEL.lower(),
        access_log=False,
    )


if __name__ == "__main__":
    main()
