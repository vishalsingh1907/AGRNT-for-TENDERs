"""
SQLAlchemy ORM model for Tender records.
Stores scraped data, AI analysis results, and notification state.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    JSON,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class Tender(Base):
    """
    Represents a single tender/bid record from any source portal.
    The `tender_id` field is unique across all sources and prevents duplicates.
    AI analysis results are stored as structured JSON in `ai_analysis`.
    """

    __tablename__ = "tenders"

    # ── Primary Key ─────────────────────────────────────────────
    id = Column(Integer, primary_key=True, autoincrement=True)

    # ── Core Tender Data ────────────────────────────────────────
    tender_id = Column(String(255), unique=True, nullable=False, index=True,
                       comment="Unique ID from the source portal")
    title = Column(Text, nullable=False)
    organization = Column(String(500), nullable=True)
    publish_date = Column(DateTime, nullable=True)
    closing_date = Column(DateTime, nullable=True)
    tender_url = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    source = Column(String(100), nullable=False, index=True,
                    comment="Source portal name (cppp, gem, ntpc, etc.)")

    # ── PDF ─────────────────────────────────────────────────────
    pdf_path = Column(String(500), nullable=True,
                      comment="Local filesystem path to downloaded PDF")

    # ── AI Analysis (Structured JSON) ──────────────────────────
    ai_score = Column(Integer, nullable=True, index=True,
                      comment="Relevance score 0-100")
    ai_analysis = Column(JSON, nullable=True,
                         comment="Full structured AI analysis result")
    is_relevant = Column(Boolean, default=False, index=True,
                         comment="True if relevant for the company profile")

    # ── Notification Tracking ──────────────────────────────────
    notified = Column(Boolean, default=False, index=True,
                      comment="True if Telegram notification was sent")

    # ── Timestamps ─────────────────────────────────────────────
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(),
                        onupdate=func.now(), nullable=False)

    # ── Indexes ────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_tenders_source_closing", "source", "closing_date"),
        Index("ix_tenders_score_notified", "ai_score", "notified"),
    )

    def __repr__(self) -> str:
        return (
            f"<Tender(id={self.id}, tender_id='{self.tender_id}', "
            f"title='{self.title[:50]}...', source='{self.source}', "
            f"score={self.ai_score})>"
        )

    def to_dict(self) -> dict:
        """Serialize to dictionary for API responses."""
        return {
            "id": self.id,
            "tender_id": self.tender_id,
            "title": self.title,
            "organization": self.organization,
            "publish_date": self.publish_date.isoformat() if self.publish_date else None,
            "closing_date": self.closing_date.isoformat() if self.closing_date else None,
            "tender_url": self.tender_url,
            "description": self.description,
            "source": self.source,
            "pdf_path": self.pdf_path,
            "ai_score": self.ai_score,
            "ai_analysis": self.ai_analysis,
            "is_relevant": self.is_relevant,
            "notified": self.notified,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
