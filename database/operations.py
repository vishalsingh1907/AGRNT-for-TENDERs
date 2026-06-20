"""
Async CRUD operations for Tender records.
Handles deduplication, upsert, querying, and statistics.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import async_session_factory
from models.tender import Tender

logger = structlog.get_logger(__name__)


class TenderRepository:
    """Async repository for Tender CRUD operations."""

    # ── Insert / Upsert ────────────────────────────────────────

    @staticmethod
    async def upsert_tender(tender_data: Dict[str, Any]) -> Optional[int]:
        """
        Insert a tender, skipping if tender_id already exists.
        Returns the tender DB id if inserted, None if skipped.
        """
        async with async_session_factory() as session:
            async with session.begin():
                stmt = (
                    sqlite_insert(Tender)
                    .values(**tender_data)
                    .on_conflict_do_nothing(index_elements=["tender_id"])
                    .returning(Tender.id)
                )
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if row:
                    logger.info("Inserted new tender", tender_id=tender_data.get("tender_id"))
                else:
                    logger.debug("Tender already exists, skipped", tender_id=tender_data.get("tender_id"))
                return row

    @staticmethod
    async def bulk_upsert_tenders(tenders: List[Dict[str, Any]]) -> int:
        """
        Bulk insert tenders, skipping duplicates.
        Returns the count of newly inserted tenders.
        """
        if not tenders:
            return 0

        inserted = 0
        async with async_session_factory() as session:
            async with session.begin():
                for tender_data in tenders:
                    stmt = (
                        sqlite_insert(Tender)
                        .values(**tender_data)
                        .on_conflict_do_nothing(index_elements=["tender_id"])
                        .returning(Tender.id)
                    )
                    result = await session.execute(stmt)
                    if result.scalar_one_or_none():
                        inserted += 1

        logger.info("Bulk upsert complete", total=len(tenders), inserted=inserted, skipped=len(tenders) - inserted)
        return inserted

    # ── Query Operations ───────────────────────────────────────

    @staticmethod
    async def get_unanalyzed_tenders(limit: int = 50) -> List[Tender]:
        """Fetch tenders that haven't been analyzed by AI yet."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(Tender)
                .where(Tender.ai_score.is_(None))
                .order_by(Tender.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    @staticmethod
    async def get_unnotified_relevant(threshold: int = 75) -> List[Tender]:
        """Fetch high-scoring tenders that haven't been notified yet."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(Tender)
                .where(
                    Tender.ai_score >= threshold,
                    Tender.notified.is_(False),
                )
                .order_by(Tender.ai_score.desc())
            )
            return list(result.scalars().all())

    @staticmethod
    async def get_latest_tenders(limit: int = 10) -> List[Tender]:
        """Get the most recently added tenders."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(Tender)
                .order_by(Tender.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    @staticmethod
    async def get_today_tenders() -> List[Tender]:
        """Get tenders added today (UTC)."""
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        async with async_session_factory() as session:
            result = await session.execute(
                select(Tender)
                .where(Tender.created_at >= today_start)
                .order_by(Tender.ai_score.desc().nullslast())
            )
            return list(result.scalars().all())

    @staticmethod
    async def search_tenders(keyword: str, limit: int = 20) -> List[Tender]:
        """Search tenders by keyword in title and description."""
        pattern = f"%{keyword}%"
        async with async_session_factory() as session:
            result = await session.execute(
                select(Tender)
                .where(
                    (Tender.title.ilike(pattern)) |
                    (Tender.description.ilike(pattern)) |
                    (Tender.organization.ilike(pattern))
                )
                .order_by(Tender.ai_score.desc().nullslast())
                .limit(limit)
            )
            return list(result.scalars().all())

    @staticmethod
    async def get_tender_by_id(tender_db_id: int) -> Optional[Tender]:
        """Get a single tender by its database ID."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(Tender).where(Tender.id == tender_db_id)
            )
            return result.scalar_one_or_none()

    # ── Update Operations ──────────────────────────────────────

    @staticmethod
    async def update_analysis(tender_id: str, analysis: Dict[str, Any]) -> None:
        """Store AI analysis results for a tender."""
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(Tender)
                    .where(Tender.tender_id == tender_id)
                    .values(
                        ai_score=analysis.get("relevance_score"),
                        ai_analysis=analysis,
                        is_relevant=analysis.get("is_relevant", False),
                        updated_at=func.now(),
                    )
                )
        logger.info("Updated AI analysis", tender_id=tender_id, score=analysis.get("relevance_score"))

    @staticmethod
    async def mark_notified(tender_id: str) -> None:
        """Mark a tender as notified via Telegram."""
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(Tender)
                    .where(Tender.tender_id == tender_id)
                    .values(notified=True, updated_at=func.now())
                )

    @staticmethod
    async def update_pdf_path(tender_id: str, pdf_path: str) -> None:
        """Store the local PDF file path."""
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(Tender)
                    .where(Tender.tender_id == tender_id)
                    .values(pdf_path=pdf_path, updated_at=func.now())
                )

    # ── Statistics ─────────────────────────────────────────────

    @staticmethod
    async def get_stats() -> Dict[str, Any]:
        """Get aggregate statistics for the dashboard."""
        async with async_session_factory() as session:
            # Total tenders
            total = await session.execute(select(func.count(Tender.id)))
            total_count = total.scalar() or 0

            # By source
            by_source = await session.execute(
                select(Tender.source, func.count(Tender.id))
                .group_by(Tender.source)
            )
            source_counts = {row[0]: row[1] for row in by_source.all()}

            # Analyzed vs unanalyzed
            analyzed = await session.execute(
                select(func.count(Tender.id)).where(Tender.ai_score.isnot(None))
            )
            analyzed_count = analyzed.scalar() or 0

            # High-scoring (relevant)
            relevant = await session.execute(
                select(func.count(Tender.id)).where(Tender.ai_score >= 75)
            )
            relevant_count = relevant.scalar() or 0

            # Notified
            notified = await session.execute(
                select(func.count(Tender.id)).where(Tender.notified.is_(True))
            )
            notified_count = notified.scalar() or 0

            # Average score
            avg_score = await session.execute(
                select(func.avg(Tender.ai_score)).where(Tender.ai_score.isnot(None))
            )
            avg = avg_score.scalar()

            # Today's tenders
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            today = await session.execute(
                select(func.count(Tender.id)).where(Tender.created_at >= today_start)
            )
            today_count = today.scalar() or 0

            # Tenders with closing date in next 7 days
            next_week = datetime.now(timezone.utc) + timedelta(days=7)
            closing_soon = await session.execute(
                select(func.count(Tender.id)).where(
                    Tender.closing_date.isnot(None),
                    Tender.closing_date <= next_week,
                    Tender.closing_date >= datetime.now(timezone.utc),
                )
            )
            closing_soon_count = closing_soon.scalar() or 0

            # Score distribution
            score_dist = await session.execute(
                select(
                    func.sum(case((Tender.ai_score < 25, 1), else_=0)).label("low"),
                    func.sum(case((Tender.ai_score.between(25, 50), 1), else_=0)).label("medium"),
                    func.sum(case((Tender.ai_score.between(51, 75), 1), else_=0)).label("high"),
                    func.sum(case((Tender.ai_score > 75, 1), else_=0)).label("very_high"),
                ).where(Tender.ai_score.isnot(None))
            )
            dist_row = score_dist.one()

            return {
                "total_tenders": total_count,
                "by_source": source_counts,
                "analyzed": analyzed_count,
                "unanalyzed": total_count - analyzed_count,
                "relevant": relevant_count,
                "notified": notified_count,
                "average_score": round(avg, 1) if avg else 0,
                "today_count": today_count,
                "closing_soon": closing_soon_count,
                "score_distribution": {
                    "0-24": dist_row.low or 0,
                    "25-50": dist_row.medium or 0,
                    "51-75": dist_row.high or 0,
                    "76-100": dist_row.very_high or 0,
                },
            }

    # ── Cleanup ────────────────────────────────────────────────

    @staticmethod
    async def delete_old_tenders(days: int = 90) -> int:
        """Delete tenders older than the specified number of days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        async with async_session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    delete(Tender).where(Tender.created_at < cutoff)
                )
                count = result.rowcount
        logger.info("Deleted old tenders", days=days, deleted=count)
        return count
