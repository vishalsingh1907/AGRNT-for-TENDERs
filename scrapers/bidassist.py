"""
Scraper for BidAssist.com — keyword-based tender search.
BidAssist provides a search-friendly URL pattern.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from scrapers.base import BaseScraper
from config.keywords import SEARCH_TERMS

logger = logging.getLogger(__name__)


class BidAssistScraper(BaseScraper):
    SOURCE_NAME = "BidAssist"
    BASE_URL = "https://www.bidassist.com"

    async def scrape(self) -> List[Dict[str, Any]]:
        """Scrape BidAssist using keyword search."""
        tenders = []
        logger.info(f"[{self.SOURCE_NAME}] Starting scrape...")

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

                # Search for each keyword
                for term in SEARCH_TERMS[:3]:  # Limit to 3 terms
                    search_url = f"https://www.bidassist.com/tenders/india?keyword={term.replace(' ', '+')}"
                    logger.info(f"[{self.SOURCE_NAME}] Searching: {term}")

                    try:
                        await page.goto(search_url, wait_until="networkidle", timeout=45000)
                        await page.wait_for_timeout(3000)

                        # BidAssist renders tender cards
                        cards = await page.query_selector_all(
                            ".card, .tender-card, [class*='tender'], .ba-card, article"
                        )

                        if not cards:
                            # Try table layout
                            cards = await page.query_selector_all("table tbody tr")

                        for card in cards:
                            try:
                                text = (await card.inner_text()).strip()
                                if not text or len(text) < 20:
                                    continue

                                # Get link
                                link_el = await card.query_selector("a")
                                url = ""
                                if link_el:
                                    href = await link_el.get_attribute("href")
                                    if href:
                                        url = href if href.startswith("http") else f"{self.BASE_URL}{href}"

                                lines = [l.strip() for l in text.split('\n') if l.strip() and len(l.strip()) > 3]
                                title = lines[0] if lines else text[:200]

                                # Extract date
                                closing_date = ""
                                date_match = re.search(r'(\d{2}[-/.]\d{2}[-/.]\d{4})', text)
                                if date_match:
                                    closing_date = date_match.group(1)

                                # Extract org
                                org = ""
                                for line in lines:
                                    if any(kw in line.lower() for kw in ["authority", "dept", "ministry", "corporation"]):
                                        org = line
                                        break

                                tenders.append(self.make_tender(
                                    title=title,
                                    organization=org,
                                    closing_date=closing_date,
                                    url=url,
                                ))
                            except Exception:
                                continue

                        await self.delay(2, 4)

                    except Exception as e:
                        logger.warning(f"[{self.SOURCE_NAME}] Search '{term}' failed: {e}")
                        continue

                await browser.close()

        except ImportError:
            logger.error(f"[{self.SOURCE_NAME}] Playwright not installed")
        except Exception as e:
            logger.error(f"[{self.SOURCE_NAME}] Scrape failed: {e}")

        # Deduplicate
        seen = set()
        unique = []
        for t in tenders:
            key = t["title"][:100].lower()
            if key not in seen:
                seen.add(key)
                unique.append(t)

        logger.info(f"[{self.SOURCE_NAME}] Found {len(unique)} unique tenders")
        return unique
