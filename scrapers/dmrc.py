"""
Scraper for Delhi Metro Rail Corporation (DMRC) tenders page.
React SPA — requires Playwright.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class DMRCScraper(BaseScraper):
    SOURCE_NAME = "DMRC"
    BASE_URL = "https://delhimetrorail.com/pages/en/tenders_by_category/7i28"

    async def scrape(self) -> List[Dict[str, Any]]:
        """Scrape DMRC tenders page using Playwright (React SPA)."""
        tenders = []
        logger.info(f"[{self.SOURCE_NAME}] Starting scrape with Playwright...")

        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=self.headers["User-Agent"],
                    ignore_https_errors=True,
                )
                page = await context.new_page()
                page.set_default_timeout(45000)

                await page.goto(self.BASE_URL, wait_until="networkidle", timeout=60000)
                await page.wait_for_timeout(5000)

                # DMRC usually renders tenders in table or card layout
                # Try table rows first
                rows = await page.query_selector_all("table tbody tr")
                if not rows:
                    # Try card-based layout
                    rows = await page.query_selector_all(".tender-item, .card, [class*='tender']")

                for row in rows:
                    try:
                        text = (await row.inner_text()).strip()
                        if not text or len(text) < 20:
                            continue

                        # Extract link
                        link_el = await row.query_selector("a")
                        url = ""
                        if link_el:
                            href = await link_el.get_attribute("href")
                            if href:
                                url = href if href.startswith("http") else f"https://delhimetrorail.com{href}"

                        # Extract date patterns
                        closing_date = ""
                        date_match = re.search(r'(\d{2}[-/.]\d{2}[-/.]\d{4})', text)
                        if date_match:
                            closing_date = date_match.group(1)

                        # Split text lines for title
                        lines = [l.strip() for l in text.split('\n') if l.strip()]
                        title = lines[0] if lines else text[:200]

                        # Extract tender ID if present
                        tender_id = ""
                        id_match = re.search(r'(DMRC[/-]\S+|[A-Z]{2,}[/-]\d+[/-]\S+)', text)
                        if id_match:
                            tender_id = id_match.group(1)

                        tenders.append(self.make_tender(
                            title=title,
                            organization="Delhi Metro Rail Corporation",
                            tender_id=tender_id,
                            closing_date=closing_date,
                            url=url,
                        ))
                    except Exception:
                        continue

                await browser.close()

        except ImportError:
            logger.error(f"[{self.SOURCE_NAME}] Playwright not installed")
        except Exception as e:
            logger.error(f"[{self.SOURCE_NAME}] Scrape failed: {e}")

        logger.info(f"[{self.SOURCE_NAME}] Found {len(tenders)} tenders")
        return tenders
