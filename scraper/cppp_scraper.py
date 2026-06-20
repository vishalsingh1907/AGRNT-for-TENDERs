"""
Scraper for the Central Public Procurement Portal (CPPP).
URL: https://eprocure.gov.in
Extracts active tenders using keyword search.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import urljoin

import structlog
from dateutil import parser as dateparser

from scraper.base import BaseScraper

logger = structlog.get_logger(__name__)


class CPPPScraper(BaseScraper):
    """Scraper for eprocure.gov.in CPPP portal."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from config.settings import settings
        self.max_pages = min(settings.MAX_PAGES_CPPP, self.max_pages)

    async def scrape(self) -> List[Dict[str, Any]]:
        all_tenders: List[Dict[str, Any]] = []

        try:
            logger.info("CPPP scraper started: broad discovery", source=self.source_name)
            # Use asyncio.wait_for to ensure the entire scrape doesn't exceed a hard limit (e.g., 5 mins)
            tenders = await asyncio.wait_for(self._fetch_latest(), timeout=300)
            all_tenders.extend(tenders)
        except asyncio.TimeoutError:
            logger.error("CPPP global timeout exceeded (5m)", source=self.source_name)
        except Exception as e:
            logger.error("CPPP fetch failed", source=self.source_name, error=str(e))

        # Deduplicate within this scrape session by tender_id
        seen = set()
        unique = []
        for t in all_tenders:
            if t["tender_id"] not in seen:
                seen.add(t["tender_id"])
                unique.append(t)

        return unique

    async def _fetch_latest(self) -> List[Dict[str, Any]]:
        """Fetch the latest active tenders broadly."""
        tenders = []
        page = await self.new_page()

        try:
            nav_start = time.perf_counter()
            logger.info("Navigation start", url=self.base_url, source=self.source_name)
            await self.safe_goto(page, self.base_url, wait_until="domcontentloaded")
            nav_duration = time.perf_counter() - nav_start
            logger.info("Navigation complete", source=self.source_name, duration_sec=round(nav_duration, 2))

            # Check for CAPTCHA or blocking
            captcha = await page.query_selector("text='CAPTCHA'")
            if captcha:
                logger.warning("CAPTCHA detected, aborting this source", source=self.source_name)
                return tenders

            # Extract tenders from the results table across pages
            for page_num in range(self.max_pages):
                logger.info("Processing page", page_num=page_num + 1, source=self.source_name)
                
                # We enforce a hard timeout of 60 seconds per page processing
                try:
                    extract_start = time.perf_counter()
                    page_tenders = await asyncio.wait_for(
                        self._extract_tenders_from_page(page), timeout=60
                    )
                    tenders.extend(page_tenders)
                    extract_duration = time.perf_counter() - extract_start
                    logger.info("Results extraction complete", count=len(page_tenders), source=self.source_name, duration_sec=round(extract_duration, 2))
                except asyncio.TimeoutError:
                    logger.error("Page extraction timed out (60s)", page_num=page_num + 1, source=self.source_name)
                    break # if a page hangs, stop paginating

                if page_num < self.max_pages - 1:
                    pag_start = time.perf_counter()
                    logger.info("Pagination start", target_page=page_num + 2, source=self.source_name)
                    has_next = await self._go_to_next_page(page)
                    pag_duration = time.perf_counter() - pag_start
                    
                    if not has_next:
                        logger.info("No more pages available", source=self.source_name, duration_sec=round(pag_duration, 2))
                        break
                    logger.info("Pagination complete", source=self.source_name, duration_sec=round(pag_duration, 2))
                    await self.rate_limit_delay()

        except Exception as e:
            logger.error("CPPP broad fetch error", source=self.source_name, error=str(e))
        finally:
            try:
                await page.close()
                logger.info("Page closed", source=self.source_name)
            except Exception:
                pass

        return tenders

    async def _extract_tenders_from_page(self, page) -> List[Dict[str, Any]]:
        """Extract tender data from the current page."""
        tenders = []

        # Common table selectors for CPPP
        row_selectors = [
            "table tbody tr",
            "table.list_table tbody tr",
            "#tender-list tr",
            ".tender-row",
            "table tr:not(:first-child)",
        ]

        rows = []
        for selector in row_selectors:
            # wait for rows to be visible
            try:
                await page.wait_for_selector(selector, state="visible", timeout=10000)
                rows = await page.query_selector_all(selector)
                if rows:
                    break
            except Exception:
                continue

        for row in rows:
            try:
                cells = await row.query_selector_all("td")
                if len(cells) < 4:
                    continue

                tender_data = await self._parse_row(cells, page)
                if tender_data and tender_data.get("tender_id"):
                    tenders.append(tender_data)

            except Exception as e:
                logger.debug("Row parse error", error=str(e))
                continue

        return tenders

    async def _parse_row(self, cells, page) -> Dict[str, Any] | None:
        """Parse a table row into tender data."""
        try:
            cell_texts = []
            for cell in cells:
                text = (await cell.inner_text()).strip()
                cell_texts.append(text)

            if len(cell_texts) < 4:
                return None

            link_element = None
            for cell in cells:
                link = await cell.query_selector("a")
                if link:
                    link_element = link
                    break

            tender_url = ""
            if link_element:
                href = await link_element.get_attribute("href")
                if href:
                    tender_url = urljoin(self.base_url, href)

            tender_id = ""
            title = ""
            organization = ""
            publish_date = None
            closing_date = None
            description = ""

            if len(cell_texts) >= 6:
                publish_date = self._parse_date(cell_texts[1])
                closing_date = self._parse_date(cell_texts[2])
                title = cell_texts[4] if len(cell_texts) > 4 else cell_texts[3]
                organization = cell_texts[5] if len(cell_texts) > 5 else ""
            elif len(cell_texts) >= 4:
                title = cell_texts[1]
                publish_date = self._parse_date(cell_texts[2])
                closing_date = self._parse_date(cell_texts[3])

            for text in cell_texts:
                if any(prefix in text.upper() for prefix in ["TENDER", "NIT", "RFP", "EOI", "/"]):
                    if len(text) < 100:
                        tender_id = text
                        break

            if not tender_id:
                tender_id = f"CPPP-{hash(title + str(publish_date))}"

            if not title:
                return None

            description = " | ".join(cell_texts)

            return {
                "tender_id": tender_id.strip()[:255],
                "title": title.strip(),
                "organization": organization.strip() or "Government of India",
                "publish_date": publish_date,
                "closing_date": closing_date,
                "tender_url": tender_url,
                "description": description,
                "source": self.source_name,
            }

        except Exception as e:
            logger.debug("Parse row error", error=str(e))
            return None

    def _parse_date(self, date_str: str) -> datetime | None:
        """Parse various date formats from CPPP."""
        if not date_str or not date_str.strip():
            return None
        try:
            return dateparser.parse(date_str.strip(), dayfirst=True)
        except (ValueError, TypeError):
            return None

    async def _go_to_next_page(self, page) -> bool:
        """Navigate to the next page of results."""
        # Combine all possible next button selectors into a single query to avoid sequential timeout delays
        selector = "a.next, a[title='Next'], li.next a, .pagination .next a, a:has-text('Next'), a:has-text('>'), a:has-text('»')"
        
        try:
            elem = await page.wait_for_selector(selector, state="visible", timeout=5000)
            if elem:
                await elem.click()
                # Wait for the next page to load instead of using fixed sleep
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
                return True
        except Exception:
            pass
        return False
