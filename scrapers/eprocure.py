"""
Scraper for eProcure.gov.in (NIC GEP platform).
The active tenders page requires CAPTCHA, so we scrape the home page
which lists the latest tenders directly, and also use Playwright
to handle the search page if available.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List
from urllib.parse import urljoin

from scrapers.base import BaseScraper
from config.keywords import SEARCH_TERMS

logger = logging.getLogger(__name__)


class EProcureScraper(BaseScraper):
    SOURCE_NAME = "eProcure.gov.in"
    BASE_URL = "https://eprocure.gov.in/eprocure/app"
    HOME_URL = "https://eprocure.gov.in/eprocure/app?page=Home&service=page"

    async def scrape(self) -> List[Dict[str, Any]]:
        """Scrape tenders from eProcure.gov.in home + active tenders via Playwright."""
        tenders = []
        logger.info(f"[{self.SOURCE_NAME}] Starting scrape...")

        # Method 1: Parse home page (has latest tenders listed without CAPTCHA)
        try:
            soup = await self.fetch_page(self.HOME_URL)
            if soup:
                tenders.extend(self._parse_home_page(soup))
        except Exception as e:
            logger.warning(f"[{self.SOURCE_NAME}] Home page parse failed: {e}")

        # Method 2: Use Playwright for active tenders with CAPTCHA
        try:
            pw_tenders = await self._scrape_with_playwright()
            tenders.extend(pw_tenders)
        except Exception as e:
            logger.warning(f"[{self.SOURCE_NAME}] Playwright scrape failed: {e}")

        # Deduplicate
        seen = set()
        unique = []
        for t in tenders:
            key = t["title"][:80].lower().strip()
            if key not in seen and len(key) > 10:
                seen.add(key)
                unique.append(t)

        logger.info(f"[{self.SOURCE_NAME}] Found {len(unique)} unique tenders")
        return unique

    def _parse_home_page(self, soup) -> List[Dict[str, Any]]:
        """Parse tenders listed on the home page."""
        tenders = []

        # The home page lists tenders as numbered links like:
        # "1. TENDER TITLE HERE"
        # Find all links that look like tender titles
        for link in soup.find_all("a"):
            text = link.get_text(strip=True)
            href = link.get("href", "")

            # Skip navigation links
            if not text or len(text) < 20:
                continue
            if any(skip in text.lower() for skip in [
                "search", "active tender", "home", "contact", "sitemap",
                "screen reader", "corrigendum", "bid award", "cppp",
                "help", "faq", "download", "archive", "status",
                "cancelled", "announcement", "recognition", "dashboard",
                "gepnic", "india.gov", "debarment", "mis report",
                "tenders by", "site compatibility", "captcha", "refresh",
                "enter captcha", "-select-", "select",
            ]):
                continue

            # Check if it looks like a tender (numbered or has tender-like URL)
            is_tender = bool(
                re.match(r'^\d+\.?\s+', text) or
                ("DirectLink" in href) or
                ("component=" in href and "page=Home" in href)
            )

            if is_tender:
                # Clean up the title (remove leading number)
                title = re.sub(r'^\d+\.?\s*', '', text).strip()
                if len(title) < 15:
                    continue

                url = urljoin("https://eprocure.gov.in", href)

                tenders.append(self.make_tender(
                    title=title,
                    organization="Govt. of India (eProcure)",
                    url=url,
                ))

        return tenders

    async def _scrape_with_playwright(self) -> List[Dict[str, Any]]:
        """Use Playwright to load the active tenders page (handles JS)."""
        tenders = []
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=self.headers["User-Agent"],
                    ignore_https_errors=True,
                )
                page = await context.new_page()
                page.set_default_timeout(30000)

                # Go to active tenders page
                active_url = "https://eprocure.gov.in/eprocure/app?page=FrontEndLatestActiveTenders&service=page"
                await page.goto(active_url, wait_until="networkidle", timeout=45000)
                await page.wait_for_timeout(3000)

                # Try to find tender listing table
                rows = await page.query_selector_all("table tr")
                for row in rows:
                    try:
                        text = (await row.inner_text()).strip()
                        if not text or len(text) < 25:
                            continue
                        # Skip headers and nav
                        text_lower = text.lower()
                        if any(skip in text_lower for skip in [
                            "s.no", "tender id", "organisation", "closing date",
                            "captcha", "refresh", "search", "-select-",
                        ]):
                            continue

                        link_el = await row.query_selector("a")
                        url = ""
                        if link_el:
                            href = await link_el.get_attribute("href")
                            if href:
                                url = urljoin("https://eprocure.gov.in", href)

                        # Extract date
                        closing_date = ""
                        date_match = re.search(r'(\d{2}[-/]\d{2}[-/]\d{4})', text)
                        if date_match:
                            closing_date = date_match.group(1)

                        # Get title from link or first long text segment
                        title = ""
                        if link_el:
                            title = (await link_el.inner_text()).strip()
                        if not title or len(title) < 15:
                            lines = [l.strip() for l in text.split('\t') if l.strip() and len(l.strip()) > 15]
                            title = lines[0] if lines else ""

                        if title and len(title) > 15:
                            tenders.append(self.make_tender(
                                title=title,
                                organization="Govt. of India (eProcure)",
                                closing_date=closing_date,
                                url=url,
                            ))
                    except Exception:
                        continue

                await browser.close()

        except ImportError:
            logger.debug(f"[{self.SOURCE_NAME}] Playwright not available for enhanced scraping")
        except Exception as e:
            logger.warning(f"[{self.SOURCE_NAME}] Playwright scrape error: {e}")

        return tenders
