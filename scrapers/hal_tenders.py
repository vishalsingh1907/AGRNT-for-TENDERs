"""
Scraper for HAL India tenders page (hal-india.co.in/tenders-details).
Angular SPA — requires Playwright.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class HALTendersScraper(BaseScraper):
    SOURCE_NAME = "HAL India"
    BASE_URL = "https://hal-india.co.in/tenders-details"

    async def scrape(self) -> List[Dict[str, Any]]:
        """Scrape HAL India tenders page using Playwright (Angular SPA)."""
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

                # HAL India renders tenders in tables — Angular-rendered
                rows = await page.query_selector_all("table tbody tr")
                if not rows:
                    # Fallback: try any table rows
                    rows = await page.query_selector_all("tr")

                for row in rows:
                    try:
                        cells = await row.query_selector_all("td")
                        if len(cells) < 2:
                            continue

                        texts = []
                        for cell in cells:
                            texts.append((await cell.inner_text()).strip())

                        # Find the link
                        link_el = await row.query_selector("a")
                        url = ""
                        if link_el:
                            href = await link_el.get_attribute("href")
                            if href:
                                url = href if href.startswith("http") else f"https://hal-india.co.in{href}"

                        # Parse fields
                        title = ""
                        tender_id = ""
                        closing_date = ""
                        for t in texts:
                            if len(t) > 30 and not title:
                                title = t
                            elif re.search(r'\d{2}[-/]\d{2}[-/]\d{4}', t) and not closing_date:
                                match = re.search(r'(\d{2}[-/]\d{2}[-/]\d{4})', t)
                                closing_date = match.group(1) if match else ""
                            elif re.search(r'[A-Z0-9]{3,}[-/]', t) and not tender_id:
                                tender_id = t[:80]

                        if title:
                            tenders.append(self.make_tender(
                                title=title,
                                organization="Hindustan Aeronautics Limited (HAL)",
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
