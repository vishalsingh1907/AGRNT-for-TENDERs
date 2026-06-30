"""
Base scraper class — all scrapers inherit from this.
Provides shared HTTP client, logging, and error handling.
"""

from __future__ import annotations

import asyncio
import random
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

import httpx
from bs4 import BeautifulSoup

from config import settings

logger = logging.getLogger(__name__)


class BaseScraper:
    """Base class for all tender scrapers."""

    SOURCE_NAME: str = "Unknown"
    BASE_URL: str = ""

    def __init__(self):
        self.headers = {
            "User-Agent": settings.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self.timeout = settings.REQUEST_TIMEOUT

    async def scrape(self) -> List[Dict[str, Any]]:
        """
        Override in subclasses. Must return a list of dicts:
        [
            {
                "title": str,
                "organization": str,
                "tender_id": str,
                "closing_date": str or None,  # DD-MM-YYYY or similar
                "url": str,
                "source": str,  # self.SOURCE_NAME
            },
            ...
        ]
        """
        raise NotImplementedError

    async def fetch_page(self, url: str, params: dict = None) -> Optional[BeautifulSoup]:
        """Fetch a page and return parsed BeautifulSoup, or None on error."""
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                headers=self.headers,
                follow_redirects=True,
                verify=False,
            ) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return BeautifulSoup(response.text, "lxml")
        except httpx.HTTPStatusError as e:
            logger.error(f"[{self.SOURCE_NAME}] HTTP {e.response.status_code} for {url}")
        except httpx.ConnectError:
            logger.error(f"[{self.SOURCE_NAME}] Connection failed for {url}")
        except httpx.TimeoutException:
            logger.error(f"[{self.SOURCE_NAME}] Timeout for {url}")
        except Exception as e:
            logger.error(f"[{self.SOURCE_NAME}] Error fetching {url}: {e}")
        return None

    async def fetch_page_raw(self, url: str, params: dict = None) -> Optional[str]:
        """Fetch raw HTML text, or None on error."""
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                headers=self.headers,
                follow_redirects=True,
                verify=False,
            ) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.text
        except Exception as e:
            logger.error(f"[{self.SOURCE_NAME}] Error fetching {url}: {e}")
        return None

    async def post_page(self, url: str, data: dict = None, json_data: dict = None) -> Optional[BeautifulSoup]:
        """POST to a page and return parsed BeautifulSoup."""
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                headers=self.headers,
                follow_redirects=True,
                verify=False,
            ) as client:
                if json_data:
                    response = await client.post(url, json=json_data)
                else:
                    response = await client.post(url, data=data)
                response.raise_for_status()
                return BeautifulSoup(response.text, "lxml")
        except Exception as e:
            logger.error(f"[{self.SOURCE_NAME}] POST error for {url}: {e}")
        return None

    def make_tender(
        self,
        title: str,
        organization: str = "",
        tender_id: str = "",
        closing_date: str = "",
        url: str = "",
    ) -> Dict[str, Any]:
        """Create a standardized tender dict."""
        return {
            "title": title.strip() if title else "N/A",
            "organization": organization.strip() if organization else "N/A",
            "tender_id": tender_id.strip() if tender_id else "N/A",
            "closing_date": closing_date.strip() if closing_date else "N/A",
            "url": url.strip() if url else "",
            "source": self.SOURCE_NAME,
        }

    async def delay(self, min_sec: float = 1.0, max_sec: float = 3.0):
        """Random delay between requests to be polite."""
        await asyncio.sleep(random.uniform(min_sec, max_sec))
