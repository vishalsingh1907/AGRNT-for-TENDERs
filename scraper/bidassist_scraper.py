"""
Scraper for BidAssist (https://www.bidassist.com).
Third-party tender aggregator — extracts tenders via search.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import urljoin

import structlog
from dateutil import parser as dateparser

from scraper.base import BaseScraper

logger = structlog.get_logger(__name__)

BIDASSIST_BASE = "https://www.bidassist.com"


class BidAssistScraper(BaseScraper):
    """Scraper for BidAssist.com tender aggregator."""

    async def scrape(self) -> List[Dict[str, Any]]:
        all_tenders: List[Dict[str, Any]] = []

        for keyword in self.search_keywords:
            try:
                tenders = await self._search_keyword(keyword)
                all_tenders.extend(tenders)
                await self.rate_limit_delay()
            except Exception as e:
                logger.error("BidAssist search failed", keyword=keyword, error=str(e))
                continue

        # Deduplicate
        seen = set()
        unique = []
        for t in all_tenders:
            if t["tender_id"] not in seen:
                seen.add(t["tender_id"])
                unique.append(t)

        return unique

    async def _search_keyword(self, keyword: str) -> List[Dict[str, Any]]:
        """Search BidAssist for a keyword."""
        tenders = []
        page = await self.new_page()

        try:
            search_url = f"{BIDASSIST_BASE}/tenders/india?keyword={keyword.replace(' ', '+')}"
            await self.safe_goto(page, search_url)
            await page.wait_for_load_state("networkidle", timeout=30000)

            # Extract tender cards/items
            for page_num in range(self.max_pages):
                page_tenders = await self._extract_tenders(page)
                tenders.extend(page_tenders)

                if page_num < self.max_pages - 1:
                    has_next = await self._go_next(page)
                    if not has_next:
                        break
                    await self.rate_limit_delay()

        except Exception as e:
            logger.error("BidAssist scrape error", keyword=keyword, error=str(e))
        finally:
            await page.close()

        return tenders

    async def _extract_tenders(self, page) -> List[Dict[str, Any]]:
        """Extract tender data from the current page."""
        tenders = []

        card_selectors = [
            ".tender-card",
            ".card",
            ".tender-item",
            ".search-result-item",
            "article",
            ".list-group-item",
        ]

        cards = []
        for selector in card_selectors:
            cards = await page.query_selector_all(selector)
            if len(cards) > 1:
                break

        for card in cards:
            try:
                tender = await self._parse_card(card)
                if tender and tender.get("tender_id"):
                    tenders.append(tender)
            except Exception as e:
                logger.debug("BidAssist card parse error", error=str(e))
                continue

        return tenders

    async def _parse_card(self, card) -> Dict[str, Any] | None:
        """Parse a BidAssist tender card."""
        try:
            text = (await card.inner_text()).strip()
            if not text or len(text) < 20:
                return None

            # Extract link
            link_el = await card.query_selector("a[href*='/tenders/']")
            if not link_el:
                link_el = await card.query_selector("a")

            tender_url = ""
            tender_id = ""
            if link_el:
                href = await link_el.get_attribute("href")
                if href:
                    tender_url = urljoin(BIDASSIST_BASE, href)
                    # Extract ID from URL
                    parts = href.rstrip("/").split("/")
                    if parts:
                        tender_id = parts[-1]

            if not tender_id:
                tender_id = f"BA-{hash(text[:100])}"

            # Extract title
            title_el = await card.query_selector("h3, h4, h5, .tender-title, .card-title, a")
            title = ""
            if title_el:
                title = (await title_el.inner_text()).strip()
            if not title:
                lines = [l.strip() for l in text.split('\n') if l.strip()]
                title = lines[0] if lines else text[:200]

            # Extract organization
            org = "BidAssist"
            org_selectors = [".org-name", ".organization", ".buyer-name", "span.text-muted"]
            for sel in org_selectors:
                org_el = await card.query_selector(sel)
                if org_el:
                    org = (await org_el.inner_text()).strip()
                    break

            # Extract dates from text
            import re
            publish_date = None
            closing_date = None
            for line in text.split('\n'):
                lower = line.lower()
                if "closing" in lower or "due" in lower or "end" in lower:
                    closing_date = self._extract_date(line)
                elif "published" in lower or "start" in lower or "posted" in lower:
                    publish_date = self._extract_date(line)

            return {
                "tender_id": tender_id.strip()[:255],
                "title": title[:500],
                "organization": org,
                "publish_date": publish_date,
                "closing_date": closing_date,
                "tender_url": tender_url,
                "description": text[:2000],
                "source": self.source_name,
            }

        except Exception:
            return None

    def _extract_date(self, text: str) -> datetime | None:
        import re
        patterns = [
            r'\d{2}[-/]\d{2}[-/]\d{4}',
            r'\d{4}[-/]\d{2}[-/]\d{2}',
            r'\d{2}\s+\w{3}\s+\d{4}',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    return dateparser.parse(match.group(0), dayfirst=True)
                except (ValueError, TypeError):
                    continue
        return None

    async def _go_next(self, page) -> bool:
        next_selectors = [
            "a[rel='next']",
            ".pagination .next a",
            "a:has-text('Next')",
            "a:has-text('>')",
        ]
        for selector in next_selectors:
            if await self.safe_click(page, selector, timeout=5000):
                await page.wait_for_load_state("networkidle", timeout=30000)
                return True
        return False
