"""
Generic PSU scraper for major Public Sector Undertakings.
Searches CPPP (eprocure.gov.in) filtered by organization name.
Supports: NTPC, BHEL, BEL, ONGC, and any PSU listed on CPPP.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import urljoin

import structlog
from dateutil import parser as dateparser

from scraper.base import BaseScraper

logger = structlog.get_logger(__name__)


class PSUScraper(BaseScraper):
    """
    Scraper for PSU tenders via CPPP.
    Filters results by organization name provided in `extra.organization_filter`.
    """

    async def scrape(self) -> List[Dict[str, Any]]:
        org_filter = self.extra.get("organization_filter", "")
        all_tenders: List[Dict[str, Any]] = []

        for keyword in self.search_keywords:
            try:
                tenders = await self._search_psu(keyword, org_filter)
                all_tenders.extend(tenders)
                await self.rate_limit_delay()
            except Exception as e:
                logger.error("PSU search failed", keyword=keyword, org=org_filter, error=str(e))
                continue

        # Deduplicate
        seen = set()
        unique = []
        for t in all_tenders:
            if t["tender_id"] not in seen:
                seen.add(t["tender_id"])
                unique.append(t)

        return unique

    async def _search_psu(self, keyword: str, org_filter: str) -> List[Dict[str, Any]]:
        """Search CPPP with keyword and filter by organization."""
        tenders = []
        page = await self.new_page()

        try:
            await self.safe_goto(page, self.base_url)
            await page.wait_for_load_state("networkidle", timeout=30000)

            # Fill search with combined keyword + org name for better results
            search_term = keyword
            search_selectors = [
                "input#search",
                "input[name='search']",
                "input[type='search']",
                "input.form-control",
                "#searchText",
            ]

            filled = False
            for selector in search_selectors:
                if await self.safe_fill(page, selector, search_term, timeout=5000):
                    filled = True
                    break

            if filled:
                submit_selectors = [
                    "input[type='submit']",
                    "button[type='submit']",
                    "#search-btn",
                    "button.btn-primary",
                ]
                for selector in submit_selectors:
                    if await self.safe_click(page, selector, timeout=5000):
                        break
                else:
                    await page.keyboard.press("Enter")

                await page.wait_for_load_state("networkidle", timeout=30000)

            # Extract and filter by organization
            for page_num in range(self.max_pages):
                page_tenders = await self._extract_filtered(page, org_filter)
                tenders.extend(page_tenders)

                if page_num < self.max_pages - 1:
                    has_next = await self._go_next(page)
                    if not has_next:
                        break
                    await self.rate_limit_delay()

        except Exception as e:
            logger.error("PSU scrape error", keyword=keyword, org=org_filter, error=str(e))
        finally:
            await page.close()

        return tenders

    async def _extract_filtered(self, page, org_filter: str) -> List[Dict[str, Any]]:
        """Extract tenders and filter by organization name."""
        tenders = []

        row_selectors = [
            "table tbody tr",
            "table.list_table tbody tr",
            "table tr:not(:first-child)",
        ]

        rows = []
        for selector in row_selectors:
            rows = await page.query_selector_all(selector)
            if rows:
                break

        for row in rows:
            try:
                cells = await row.query_selector_all("td")
                if len(cells) < 4:
                    continue

                cell_texts = []
                for cell in cells:
                    text = (await cell.inner_text()).strip()
                    cell_texts.append(text)

                # Check if this row matches the organization filter
                row_text = " ".join(cell_texts).upper()
                if org_filter and org_filter.upper() not in row_text:
                    continue

                # Parse the row data
                tender_data = self._parse_psu_row(cell_texts, cells, page)
                if tender_data:
                    tenders.append(tender_data)

            except Exception as e:
                logger.debug("PSU row parse error", error=str(e))
                continue

        logger.debug("PSU tenders extracted", count=len(tenders), org=org_filter)
        return tenders

    def _parse_psu_row(self, cell_texts: list, cells: list, page) -> Dict[str, Any] | None:
        """Parse a table row into tender data."""
        try:
            if len(cell_texts) < 4:
                return None

            # Flexible column mapping
            tender_id = ""
            title = ""
            organization = ""
            publish_date = None
            closing_date = None

            if len(cell_texts) >= 6:
                publish_date = self._parse_date(cell_texts[1])
                closing_date = self._parse_date(cell_texts[2])
                title = cell_texts[4] if len(cell_texts) > 4 else cell_texts[3]
                organization = cell_texts[5] if len(cell_texts) > 5 else self.extra.get("organization_filter", "PSU")
            elif len(cell_texts) >= 4:
                title = cell_texts[1]
                publish_date = self._parse_date(cell_texts[2])
                closing_date = self._parse_date(cell_texts[3])
                organization = self.extra.get("organization_filter", "PSU")

            # Generate tender ID
            for text in cell_texts:
                if "/" in text and len(text) < 100:
                    tender_id = text
                    break

            if not tender_id:
                tender_id = f"{self.source_name}-{hash(title + str(publish_date))}"

            if not title:
                return None

            return {
                "tender_id": tender_id.strip()[:255],
                "title": title.strip(),
                "organization": organization.strip(),
                "publish_date": publish_date,
                "closing_date": closing_date,
                "tender_url": self.base_url,
                "description": " | ".join(cell_texts),
                "source": self.source_name,
            }

        except Exception:
            return None

    def _parse_date(self, date_str: str) -> datetime | None:
        if not date_str or not date_str.strip():
            return None
        try:
            return dateparser.parse(date_str.strip(), dayfirst=True)
        except (ValueError, TypeError):
            return None

    async def _go_next(self, page) -> bool:
        next_selectors = [
            "a.next", "a[title='Next']", ".pagination .next a",
            "a:has-text('Next')", "a:has-text('>')",
        ]
        for selector in next_selectors:
            if await self.safe_click(page, selector, timeout=5000):
                await page.wait_for_load_state("networkidle", timeout=30000)
                return True
        return False
