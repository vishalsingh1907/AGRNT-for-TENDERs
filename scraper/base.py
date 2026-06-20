"""
Abstract base scraper with Playwright browser management,
retry logic, rate limiting, and resource cleanup.
"""

from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import structlog
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import settings

logger = structlog.get_logger(__name__)


class BaseScraper(ABC):
    """
    Abstract base class for all tender scrapers.
    Manages Playwright browser lifecycle and provides common utilities.
    """

    def __init__(
        self,
        source_name: str,
        base_url: str,
        search_keywords: List[str] | None = None,
        max_pages: int = 5,
        extra: Dict[str, Any] | None = None,
    ):
        self.source_name = source_name
        self.base_url = base_url
        self.search_keywords = search_keywords or []
        self.max_pages = min(max_pages, settings.MAX_PAGES_PER_SOURCE)
        self.extra = extra or {}
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    async def new_page(self) -> Page:
        """Create a new page in the browser context."""
        if not self._context:
            raise RuntimeError("Browser context not initialized.")
        page = await self._context.new_page()
        page.set_default_timeout(settings.SCRAPE_TIMEOUT_MS)
        logger.info("Page created", source=self.source_name)
        return page

    async def rate_limit_delay(self) -> None:
        """Random delay between requests to respect rate limits."""
        delay = random.uniform(settings.SCRAPE_DELAY_MIN, settings.SCRAPE_DELAY_MAX)
        logger.debug("Rate limit delay", seconds=round(delay, 2), source=self.source_name)
        await asyncio.sleep(delay)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((TimeoutError, Exception)),
        reraise=True,
    )
    async def safe_goto(self, page: Page, url: str, wait_until: str = "domcontentloaded") -> None:
        """Navigate to URL with retry logic."""
        logger.debug("Navigation start", url=url, source=self.source_name)
        await page.goto(url, wait_until=wait_until, timeout=settings.SCRAPE_TIMEOUT_MS)
        logger.debug("Navigation complete", url=url, source=self.source_name)

    async def safe_click(self, page: Page, selector: str, timeout: int = 10000) -> bool:
        """Click an element safely, returning False if not found."""
        try:
            await page.wait_for_selector(selector, state="visible", timeout=timeout)
            await page.click(selector)
            return True
        except Exception:
            logger.debug("Element not found for click", selector=selector, source=self.source_name)
            return False

    async def safe_fill(self, page: Page, selector: str, value: str, timeout: int = 10000) -> bool:
        """Fill an input field safely."""
        try:
            await page.wait_for_selector(selector, state="visible", timeout=timeout)
            await page.fill(selector, value)
            return True
        except Exception:
            logger.debug("Element not found for fill", selector=selector, source=self.source_name)
            return False

    async def safe_text(self, page: Page, selector: str, default: str = "") -> str:
        """Extract text from an element safely."""
        try:
            element = await page.query_selector(selector)
            if element:
                return (await element.inner_text()).strip()
        except Exception:
            pass
        return default

    async def safe_attribute(self, page: Page, selector: str, attr: str, default: str = "") -> str:
        """Get element attribute safely."""
        try:
            element = await page.query_selector(selector)
            if element:
                val = await element.get_attribute(attr)
                return val.strip() if val else default
        except Exception:
            pass
        return default

    @abstractmethod
    async def scrape(self) -> List[Dict[str, Any]]:
        """
        Scrape tenders from the source.
        Must return a list of dicts with keys:
            tender_id, title, organization, publish_date,
            closing_date, tender_url, description, source
        """
        ...

    async def run(self) -> List[Dict[str, Any]]:
        """
        Execute the scraper with full lifecycle management.
        Returns scraped tender data.
        """
        logger.info("Starting scrape", source=self.source_name)
        
        try:
            async with async_playwright() as p:
                logger.info("Playwright started", source=self.source_name)
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                logger.info("Browser launch", source=self.source_name)
                
                try:
                    context = await browser.new_context(
                        user_agent=(
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/131.0.0.0 Safari/537.36"
                        ),
                        viewport={"width": 1920, "height": 1080},
                        java_script_enabled=True,
                    )
                    logger.info("Context creation", source=self.source_name)
                    
                    self._context = context
                    try:
                        tenders = await self.scrape()
                        logger.info(
                            "Scrape completed",
                            source=self.source_name,
                            tenders_found=len(tenders),
                        )
                        return tenders
                    finally:
                        await context.close()
                        self._context = None
                        logger.info("Context closed", source=self.source_name)
                finally:
                    await browser.close()
                    logger.info("Browser close", source=self.source_name)
        except Exception as e:
            logger.error(
                "Scrape failed",
                source=self.source_name,
                error=str(e),
                exc_info=True,
            )
            return []
