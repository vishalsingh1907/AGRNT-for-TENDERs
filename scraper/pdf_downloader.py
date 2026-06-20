"""
PDF download and text extraction utility.
Downloads tender PDFs and extracts text for AI analysis.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import aiofiles
import httpx
import structlog
from PyPDF2 import PdfReader
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings

logger = structlog.get_logger(__name__)

MAX_PDF_SIZE_MB = 50
MAX_PDF_SIZE_BYTES = MAX_PDF_SIZE_MB * 1024 * 1024


class PDFDownloader:
    """Downloads tender PDFs and extracts text content."""

    def __init__(self):
        self.download_dir = settings.pdf_dir

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=15))
    async def download(self, url: str, source: str, tender_id: str) -> Optional[str]:
        """
        Download a PDF from the given URL.
        Returns the local file path if successful, None otherwise.
        """
        if not url or not url.strip():
            return None

        # Sanitize tender_id for filesystem
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in tender_id)
        save_dir = self.download_dir / source / safe_id
        save_dir.mkdir(parents=True, exist_ok=True)

        filename = url.split("/")[-1].split("?")[0]
        if not filename.endswith(".pdf"):
            filename = f"{safe_id}.pdf"
        save_path = save_dir / filename

        # Skip if already downloaded
        if save_path.exists():
            logger.debug("PDF already downloaded", path=str(save_path))
            return str(save_path)

        try:
            async with httpx.AsyncClient(
                timeout=60.0,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
                    )
                },
            ) as client:
                # Check content length first
                head_resp = await client.head(url)
                content_length = int(head_resp.headers.get("content-length", 0))
                if content_length > MAX_PDF_SIZE_BYTES:
                    logger.warning("PDF too large, skipping", url=url, size_mb=content_length / 1024 / 1024)
                    return None

                # Download
                resp = await client.get(url)
                resp.raise_for_status()

                if len(resp.content) > MAX_PDF_SIZE_BYTES:
                    logger.warning("PDF too large after download", url=url)
                    return None

                async with aiofiles.open(save_path, "wb") as f:
                    await f.write(resp.content)

            logger.info("PDF downloaded", path=str(save_path), size_kb=len(resp.content) // 1024)
            return str(save_path)

        except Exception as e:
            logger.error("PDF download failed", url=url, error=str(e))
            return None

    @staticmethod
    async def extract_text(pdf_path: str, max_pages: int = 20) -> str:
        """
        Extract text content from a PDF file.
        Runs in a thread pool to avoid blocking the event loop.
        """
        try:
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(
                None, _extract_pdf_text_sync, pdf_path, max_pages
            )
            return text
        except Exception as e:
            logger.error("PDF text extraction failed", path=pdf_path, error=str(e))
            return ""


def _extract_pdf_text_sync(pdf_path: str, max_pages: int) -> str:
    """Synchronous PDF text extraction (runs in thread pool)."""
    try:
        reader = PdfReader(pdf_path)
        text_parts = []
        for i, page in enumerate(reader.pages):
            if i >= max_pages:
                break
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
        return "\n\n".join(text_parts)
    except Exception as e:
        logger.error("PDF read error", path=pdf_path, error=str(e))
        return ""
