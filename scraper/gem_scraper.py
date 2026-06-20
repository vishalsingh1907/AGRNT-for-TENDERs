"""
Scraper for Government e-Marketplace (GeM).
URL: https://bidplus.gem.gov.in/all-bids
Extracts active bids and tenders.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import urljoin

import structlog
from dateutil import parser as dateparser

from scraper.base import BaseScraper

logger = structlog.get_logger(__name__)

GEM_BASE = "https://bidplus.gem.gov.in"


class GeMScraper(BaseScraper):
    """Scraper for GeM bidding portal."""

    async def scrape(self) -> List[Dict[str, Any]]:
        all_tenders: List[Dict[str, Any]] = []

        for keyword in self.search_keywords:
            try:
                tenders = await self._search_keyword(keyword)
                all_tenders.extend(tenders)
                await self.rate_limit_delay()
            except Exception as e:
                logger.error("GeM keyword search failed", keyword=keyword, error=str(e))
                continue

        # Deduplicate by tender_id
        seen = set()
        unique = []
        for t in all_tenders:
            if t["tender_id"] not in seen:
                seen.add(t["tender_id"])
                unique.append(t)

        return unique

    async def _search_keyword(self, keyword: str) -> List[Dict[str, Any]]:
        """Search GeM for a specific keyword."""
        tenders = []
        page = await self.new_page()

        try:
            # Navigate to the bids listing page
            await self.safe_goto(page, self.base_url)
            await page.wait_for_load_state("networkidle", timeout=30000)

            # Try to search
            search_selectors = [
                "#searchBid",
                "input[name='searchBid']",
                "input[placeholder*='Search']",
                "input.search-input",
                "#search",
                "input[type='search']",
            ]

            filled = False
            for selector in search_selectors:
                if await self.safe_fill(page, selector, keyword, timeout=5000):
                    filled = True
                    break

            if filled:
                submit_selectors = [
                    "#searchBidRA",
                    "button[type='submit']",
                    "button.search-btn",
                    "input[type='submit']",
                ]
                for selector in submit_selectors:
                    if await self.safe_click(page, selector, timeout=5000):
                        break
                else:
                    await page.keyboard.press("Enter")

                await page.wait_for_load_state("networkidle", timeout=30000)
                await self.rate_limit_delay()

            # Extract bids from the listing
            for page_num in range(self.max_pages):
                page_tenders = await self._extract_bids(page)
                tenders.extend(page_tenders)

                if page_num < self.max_pages - 1:
                    has_next = await self._go_next(page)
                    if not has_next:
                        break
                    await self.rate_limit_delay()

        except Exception as e:
            logger.error("GeM scrape error", keyword=keyword, error=str(e))
        finally:
            await page.close()

        return tenders

    async def _extract_bids(self, page) -> List[Dict[str, Any]]:
        """Extract bid data from the current page."""
        tenders = []

        # GeM bid cards / list items
        card_selectors = [
            ".bid-card",
            ".card.bid",
            "#pagi_content .border",
            ".bid-listing-item",
            "div[id^='bidN']",
            ".list-group-item",
        ]

        cards = []
        for selector in card_selectors:
            cards = await page.query_selector_all(selector)
            if cards:
                break

        # If no cards found, try table rows
        if not cards:
            cards = await page.query_selector_all("table tbody tr")

        for card in cards:
            try:
                tender = await self._parse_bid_card(card)
                if tender and tender.get("tender_id"):
                    tenders.append(tender)
            except Exception as e:
                logger.debug("GeM bid parse error", error=str(e))
                continue

        logger.debug("GeM bids extracted", count=len(tenders))
        return tenders

    async def _parse_bid_card(self, card) -> Dict[str, Any] | None:
        """Parse a GeM bid card into tender data."""
        try:
            text = (await card.inner_text()).strip()
            if not text or len(text) < 20:
                return None

            # Extract bid number (GEM/XXXX/XXXX/XXXXXXX)
            tender_id = ""
            link_el = await card.query_selector("a[href*='/showbidDocument']")
            if not link_el:
                link_el = await card.query_selector("a[href*='bid']")
            if not link_el:
                link_el = await card.query_selector("a")

            tender_url = ""
            if link_el:
                href = await link_el.get_attribute("href")
                if href:
                    tender_url = urljoin(GEM_BASE, href)
                    # Extract bid number from URL or text
                    if "/showbidDocument/" in href:
                        tender_id = href.split("/showbidDocument/")[-1]

            # Try to find bid number in text
            if not tender_id:
                import re
                gem_pattern = re.compile(r'GEM/\d{4}/B/\d+', re.IGNORECASE)
                match = gem_pattern.search(text)
                if match:
                    tender_id = match.group(0)

            if not tender_id:
                tender_id = f"GEM-{hash(text[:100])}"

            # Extract title - first significant text line
            lines = [l.strip() for l in text.split('\n') if l.strip() and len(l.strip()) > 10]
            title = lines[0] if lines else text[:200]

            # Extract organization/department
            organization = "GeM"
            for line in lines:
                lower = line.lower()
                if any(word in lower for word in ["ministry", "department", "corporation", "limited", "board", "authority"]):
                    organization = line[:200]
                    break

            # Extract dates from text
            publish_date = None
            closing_date = None
            for line in lines:
                lower = line.lower()
                if "start" in lower or "publish" in lower or "created" in lower:
                    publish_date = self._extract_date(line)
                elif "end" in lower or "closing" in lower or "due" in lower:
                    closing_date = self._extract_date(line)

            return {
                "tender_id": tender_id.strip()[:255],
                "title": title[:500],
                "organization": organization,
                "publish_date": publish_date,
                "closing_date": closing_date,
                "tender_url": tender_url,
                "description": text[:2000],
                "source": self.source_name,
            }

        except Exception as e:
            logger.debug("Bid card parse error", error=str(e))
            return None

    def _extract_date(self, text: str) -> datetime | None:
        """Extract date from a text line."""
        import re
        # Common date patterns
        date_patterns = [
            r'\d{2}[-/]\d{2}[-/]\d{4}',
            r'\d{4}[-/]\d{2}[-/]\d{2}',
            r'\d{2}\s+\w{3}\s+\d{4}',
            r'\w{3}\s+\d{2},?\s+\d{4}',
        ]
        for pattern in date_patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    return dateparser.parse(match.group(0), dayfirst=True)
                except (ValueError, TypeError):
                    continue
        return None

    async def _go_next(self, page) -> bool:
        """Navigate to the next page."""
        next_selectors = [
            "a[aria-label='Next']",
            ".pagination .next a",
            "a:has-text('Next')",
            "li.next a",
            "a:has-text('»')",
        ]
        for selector in next_selectors:
            if await self.safe_click(page, selector, timeout=5000):
                await page.wait_for_load_state("networkidle", timeout=30000)
                return True
        return False
