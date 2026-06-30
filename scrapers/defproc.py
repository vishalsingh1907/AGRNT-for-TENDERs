"""
Scraper for DefProc.gov.in (Defence Procurement NIC GEP platform).
Same NIC GEP framework as eprocure.gov.in.
Home page lists latest tenders without CAPTCHA.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List
from urllib.parse import urljoin

from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class DefProcScraper(BaseScraper):
    SOURCE_NAME = "DefProc (MoD)"
    BASE_URL = "https://defproc.gov.in/nicgep/app"
    HOME_URL = "https://defproc.gov.in/nicgep/app?page=Home&service=page"

    async def scrape(self) -> List[Dict[str, Any]]:
        """Scrape tenders from DefProc.gov.in home page."""
        tenders = []
        logger.info(f"[{self.SOURCE_NAME}] Starting scrape...")

        try:
            soup = await self.fetch_page(self.HOME_URL)
            if not soup:
                # Fallback to base URL
                soup = await self.fetch_page(self.BASE_URL)
            if not soup:
                logger.warning(f"[{self.SOURCE_NAME}] Could not fetch page")
                return tenders

            tenders.extend(self._parse_home_page(soup))

        except Exception as e:
            logger.error(f"[{self.SOURCE_NAME}] Scrape failed: {e}")

        # Also try active tenders via Playwright
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
        """Parse tenders from the home page (listed as numbered links)."""
        tenders = []

        for link in soup.find_all("a"):
            text = link.get_text(strip=True)
            href = link.get("href", "")

            if not text or len(text) < 20:
                continue

            # Skip navigation links
            if any(skip in text.lower() for skip in [
                "search", "active tender", "home", "contact", "sitemap",
                "screen reader", "corrigendum", "bid award", "cppp",
                "help", "faq", "download", "archive", "status",
                "cancelled", "announcement", "recognition", "dashboard",
                "gepnic", "india.gov", "debarment", "mis report",
                "tenders by", "site compatibility", "captcha", "refresh",
                "enter captcha", "-select-", "select", "more...",
                "bidders manual", "feedback", "dsc", "online bidder",
                "password", "nodal officer", "hassle free", "guidelines",
                "portal policies", "informatics", "contractor",
            ]):
                continue

            # Check if it looks like a tender link
            is_tender = bool(
                re.match(r'^\d+\.?\s+', text) or
                ("DirectLink" in href and "page=Home" in href)
            )

            if is_tender:
                title = re.sub(r'^\d+\.?\s*', '', text).strip()
                if len(title) < 15:
                    continue

                url = urljoin("https://defproc.gov.in", href)

                tenders.append(self.make_tender(
                    title=title,
                    organization="Ministry of Defence",
                    url=url,
                ))

        return tenders

    async def _scrape_with_playwright(self) -> List[Dict[str, Any]]:
        """Use Playwright to load active tenders page."""
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

                active_url = "https://defproc.gov.in/nicgep/app?page=FrontEndLatestActiveTenders&service=page"
                await page.goto(active_url, wait_until="networkidle", timeout=45000)
                await page.wait_for_timeout(3000)

                rows = await page.query_selector_all("table tr")
                for row in rows:
                    try:
                        text = (await row.inner_text()).strip()
                        if not text or len(text) < 25:
                            continue
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
                                url = urljoin("https://defproc.gov.in", href)

                        closing_date = ""
                        date_match = re.search(r'(\d{2}[-/]\d{2}[-/]\d{4})', text)
                        if date_match:
                            closing_date = date_match.group(1)

                        title = ""
                        if link_el:
                            title = (await link_el.inner_text()).strip()
                        if not title or len(title) < 15:
                            lines = [l.strip() for l in text.split('\t') if l.strip() and len(l.strip()) > 15]
                            title = lines[0] if lines else ""

                        if title and len(title) > 15:
                            tenders.append(self.make_tender(
                                title=title,
                                organization="Ministry of Defence",
                                closing_date=closing_date,
                                url=url,
                            ))
                    except Exception:
                        continue

                await browser.close()

        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"[{self.SOURCE_NAME}] Playwright error: {e}")

        return tenders
