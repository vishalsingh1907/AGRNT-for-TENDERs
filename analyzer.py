"""
Keyword-based relevance analyzer for Kapoor Engineers.
Matches tender titles and organizations against known keywords.
No AI, no database — pure string matching.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from config.keywords import RELEVANT_KEYWORDS

logger = logging.getLogger(__name__)


def analyze_relevance(tenders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filter tenders to only those relevant to Kapoor Engineers.

    Returns tenders with relevance_score >= 1 (at least 1 keyword match).
    Each tender dict gets extra fields:
        - relevance_score: int (number of matched keywords)
        - matched_keywords: list[str] (which keywords matched)
    """
    relevant = []

    for tender in tenders:
        # Combine title + org into searchable text
        search_text = " ".join([
            (tender.get("title") or ""),
            (tender.get("organization") or ""),
        ]).lower()

        # Clean up the text
        search_text = re.sub(r'[^a-z0-9\s/]', ' ', search_text)
        search_text = re.sub(r'\s+', ' ', search_text)

        matched = []
        for keyword in RELEVANT_KEYWORDS:
            kw_lower = keyword.lower()
            # Use word boundary matching for short keywords to avoid false positives
            if len(kw_lower) <= 3:
                # For very short keywords (plc, hmi, bms, etc.), require word boundary
                pattern = r'\b' + re.escape(kw_lower) + r'\b'
                if re.search(pattern, search_text):
                    matched.append(keyword)
            else:
                if kw_lower in search_text:
                    matched.append(keyword)

        if matched:
            tender["relevance_score"] = len(matched)
            tender["matched_keywords"] = matched
            relevant.append(tender)

    # Sort by relevance score (most relevant first)
    relevant.sort(key=lambda t: t["relevance_score"], reverse=True)

    logger.info(
        f"Relevance analysis: {len(relevant)} relevant out of {len(tenders)} total tenders"
    )

    return relevant
