"""
Scraper for HAL eProcurement Portal (eproc.hal-india.co.in).
This is a complex TenderWizard JSP site — requires Playwright.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class HALEprocScraper(BaseScraper):
    SOURCE_NAME = "HAL eProcurement"
    BASE_URL = "https://eproc.hal-india.co.in/HAL/"

    async def scrape(self) -> List[Dict[str, Any]]:
        """Scrape HAL eProcurement portal using Playwright."""
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

                # Navigate to the portal
                await page.goto(self.BASE_URL, wait_until="networkidle", timeout=60000)
                await page.wait_for_timeout(3000)

                # Try to find and click on "Published Tenders" or similar link
                try:
                    # Look for published/active tenders link
                    links = await page.query_selector_all("a")
                    for link in links:
                        text = (await link.inner_text()).strip().lower()
                        if "published" in text or "active" in text or "open" in text:
                            await link.click()
                            await page.wait_for_timeout(3000)
                            break
                except Exception:
                    pass

                # Try to extract tender data from tables
                rows = await page.query_selector_all("table tr")
                for row in rows:
                    cells = await row.query_selector_all("td")
                    if len(cells) >= 3:
                        try:
                            texts = []
                            for cell in cells:
                                texts.append((await cell.inner_text()).strip())

                            # Try to find a link in the row
                            link_el = await row.query_selector("a")
                            url = ""
                            if link_el:
                                href = await link_el.get_attribute("href")
                                if href:
                                    url = href if href.startswith("http") else f"https://eproc.hal-india.co.in{href}"

                            # Heuristic: first substantial text is title
                            title = ""
                            tender_id = ""
                            closing_date = ""
                            for t in texts:
                                if len(t) > 30 and not title:
                                    title = t
                                elif re.search(r'\d{2}[-/]\d{2}[-/]\d{4}', t) and not closing_date:
                                    match = re.search(r'(\d{2}[-/]\d{2}[-/]\d{4})', t)
                                    closing_date = match.group(1) if match else ""
                                elif re.search(r'[A-Z]{2,}[-/]\d+', t) and not tender_id:
                                    tender_id = t

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
            logger.error(f"[{self.SOURCE_NAME}] Playwright not installed. Run: playwright install chromium")
        except Exception as e:
            logger.error(f"[{self.SOURCE_NAME}] Scrape failed: {e}")

        logger.info(f"[{self.SOURCE_NAME}] Found {len(tenders)} tenders")
        return tenders
