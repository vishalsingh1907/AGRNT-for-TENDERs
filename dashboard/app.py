"""
FastAPI admin dashboard with Jinja2 templates.
Provides web UI for viewing tenders, stats, and system health.
Also exposes API endpoints for programmatic access.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config.settings import settings
from database.operations import TenderRepository

logger = structlog.get_logger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"

# Track app start time for uptime
_app_start_time = datetime.now(timezone.utc)
_last_cycle_stats: dict = {}


def set_last_cycle_stats(stats: dict) -> None:
    """Update the last cycle stats (called from scheduler)."""
    global _last_cycle_stats
    _last_cycle_stats = stats


def create_app() -> FastAPI:
    """Create and configure the FastAPI dashboard application."""
    app = FastAPI(
        title="Tender Monitoring Agent",
        description="AI-powered tender monitoring dashboard",
        version="1.0.0",
    )

    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

    # ── Health Check ────────────────────────────────────────────

    @app.get("/health", response_class=JSONResponse)
    async def health_check():
        """System health check endpoint."""
        uptime = (datetime.now(timezone.utc) - _app_start_time).total_seconds()
        return {
            "status": "healthy",
            "uptime_seconds": round(uptime, 1),
            "uptime_human": _format_duration(uptime),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ai_provider": settings.AI_PROVIDER,
            "ai_model": settings.AI_MODEL,
            "scrape_interval_hours": settings.SCRAPE_INTERVAL_HOURS,
            "relevance_threshold": settings.RELEVANCE_THRESHOLD,
            "last_cycle": _last_cycle_stats or "No cycle completed yet",
        }

    # ── Dashboard Pages ─────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def dashboard_home(request: Request):
        """Main dashboard page with stats overview."""
        stats = await TenderRepository.get_stats()
        latest = await TenderRepository.get_latest_tenders(limit=10)
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "stats": stats,
                "tenders": latest,
                "now": datetime.now(timezone.utc),
            },
        )

    @app.get("/tenders", response_class=HTMLResponse)
    async def tenders_page(
        request: Request,
        search: Optional[str] = Query(None),
        source: Optional[str] = Query(None),
        min_score: Optional[int] = Query(None),
    ):
        """Tenders listing page with search and filters."""
        if search:
            tenders = await TenderRepository.search_tenders(search, limit=50)
        else:
            tenders = await TenderRepository.get_latest_tenders(limit=50)

        # Apply filters
        if source:
            tenders = [t for t in tenders if t.source == source]
        if min_score is not None:
            tenders = [t for t in tenders if t.ai_score and t.ai_score >= min_score]

        stats = await TenderRepository.get_stats()
        return templates.TemplateResponse(
            "tenders.html",
            {
                "request": request,
                "tenders": tenders,
                "search": search or "",
                "source": source or "",
                "min_score": min_score,
                "sources": list(stats.get("by_source", {}).keys()),
            },
        )

    @app.get("/tender/{tender_id}", response_class=HTMLResponse)
    async def tender_detail(request: Request, tender_id: int):
        """Single tender detail page."""
        tender = await TenderRepository.get_tender_by_id(tender_id)
        if not tender:
            return HTMLResponse("<h1>Tender not found</h1>", status_code=404)
        return templates.TemplateResponse(
            "detail.html",
            {"request": request, "tender": tender},
        )

    @app.get("/logs", response_class=HTMLResponse)
    async def logs_page(request: Request):
        """Logging dashboard page."""
        return templates.TemplateResponse(
            "logs.html",
            {
                "request": request,
                "last_cycle": _last_cycle_stats,
                "uptime": _format_duration(
                    (datetime.now(timezone.utc) - _app_start_time).total_seconds()
                ),
                "config": {
                    "ai_provider": settings.AI_PROVIDER,
                    "ai_model": settings.AI_MODEL,
                    "scrape_interval": f"{settings.SCRAPE_INTERVAL_HOURS}h",
                    "relevance_threshold": settings.RELEVANCE_THRESHOLD,
                    "sources_config": settings.SOURCES_CONFIG_PATH,
                },
            },
        )

    # ── API Endpoints ───────────────────────────────────────────

    @app.get("/api/stats", response_class=JSONResponse)
    async def api_stats():
        """Get statistics as JSON."""
        return await TenderRepository.get_stats()

    @app.get("/api/tenders", response_class=JSONResponse)
    async def api_tenders(
        search: Optional[str] = Query(None),
        limit: int = Query(20, le=100),
    ):
        """Get tenders as JSON."""
        if search:
            tenders = await TenderRepository.search_tenders(search, limit=limit)
        else:
            tenders = await TenderRepository.get_latest_tenders(limit=limit)
        return [t.to_dict() for t in tenders]

    @app.get("/api/tender/{tender_id}", response_class=JSONResponse)
    async def api_tender_detail(tender_id: int):
        """Get single tender as JSON."""
        tender = await TenderRepository.get_tender_by_id(tender_id)
        if not tender:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return tender.to_dict()

    return app


def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
