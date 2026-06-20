"""
AI Tender Analyzer using Google Gemini (primary) with OpenAI fallback.
Supports structured JSON output via Pydantic schemas.
Includes rate limiting, retries, and batch processing.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ai.prompts import SYSTEM_PROMPT, TenderAnalysis, build_analysis_prompt
from config.settings import settings

logger = structlog.get_logger(__name__)


class TenderAnalyzer:
    """
    Analyzes tender relevance using AI.
    Primary: Google Gemini with structured output.
    Fallback: OpenAI with JSON mode.
    """

    def __init__(self):
        self.provider = settings.AI_PROVIDER.lower()
        self.model = settings.AI_MODEL
        self._request_count = 0
        self._last_reset = asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0
        self._gemini_client = None
        self._openai_client = None

    def _get_gemini_client(self):
        """Lazy-initialize Gemini client."""
        if self._gemini_client is None:
            from google import genai
            self._gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return self._gemini_client

    def _get_openai_client(self):
        """Lazy-initialize OpenAI client."""
        if self._openai_client is None:
            from openai import AsyncOpenAI
            self._openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        return self._openai_client

    async def _rate_limit(self) -> None:
        """Simple rate limiter: max AI_MAX_RPM requests per minute."""
        loop = asyncio.get_event_loop()
        now = loop.time()
        if now - self._last_reset > 60:
            self._request_count = 0
            self._last_reset = now

        if self._request_count >= settings.AI_MAX_RPM:
            wait_time = 60 - (now - self._last_reset)
            if wait_time > 0:
                logger.info("AI rate limit reached, waiting", wait_seconds=round(wait_time, 1))
                await asyncio.sleep(wait_time)
            self._request_count = 0
            self._last_reset = loop.time()

        self._request_count += 1

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        retry=retry_if_exception_type((Exception,)),
        reraise=True,
    )
    async def analyze(self, tender_data: Dict[str, Any], pdf_text: str = "") -> Dict[str, Any]:
        """
        Analyze a single tender and return structured results.
        Returns a dict matching the TenderAnalysis schema.
        """
        await self._rate_limit()

        prompt = build_analysis_prompt(
            title=tender_data.get("title", ""),
            organization=tender_data.get("organization", ""),
            tender_id=tender_data.get("tender_id", ""),
            publish_date=str(tender_data.get("publish_date", "")),
            closing_date=str(tender_data.get("closing_date", "")),
            source=tender_data.get("source", ""),
            description=tender_data.get("description", ""),
            pdf_text=pdf_text,
        )

        try:
            if self.provider == "gemini":
                result = await self._analyze_gemini(prompt)
            elif self.provider == "openai":
                result = await self._analyze_openai(prompt)
            else:
                raise ValueError(f"Unknown AI provider: {self.provider}")

            # Apply Hybrid Filtering: Base AI Score + Keyword Bonus
            # Add +5 per matched keyword, capped at +20
            from config.settings import RELEVANT_KEYWORDS
            text_for_bonus = (prompt).upper()
            bonus_matched = [kw for kw in RELEVANT_KEYWORDS if kw.upper() in text_for_bonus]
            bonus_points = min(20, len(bonus_matched) * 5)
            
            final_score = min(100, result.get("relevance_score", 0) + bonus_points)
            result["relevance_score"] = final_score
            # Ensure is_relevant matches the final score threshold (50+)
            result["is_relevant"] = final_score >= 50

            logger.info(
                "Tender analyzed",
                tender_id=tender_data.get("tender_id"),
                score=final_score,
                bonus=bonus_points,
                action=result.get("recommended_action"),
            )
            return result

        except Exception as e:
            logger.error(
                "AI analysis failed",
                tender_id=tender_data.get("tender_id"),
                provider=self.provider,
                error=str(e),
            )
            # Return a safe fallback
            return self._fallback_analysis(tender_data)

    async def _analyze_gemini(self, prompt: str) -> Dict[str, Any]:
        """Analyze using Google Gemini with structured output."""
        client = self._get_gemini_client()

        # Run in executor since google-genai may not be fully async
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": TenderAnalysis,
                    "system_instruction": SYSTEM_PROMPT,
                },
            ),
        )

        # Parse the structured response
        if hasattr(response, "parsed") and response.parsed:
            return response.parsed.model_dump()

        # Fallback: parse JSON text
        text = response.text.strip()
        data = json.loads(text)
        analysis = TenderAnalysis(**data)
        return analysis.model_dump()

    async def _analyze_openai(self, prompt: str) -> Dict[str, Any]:
        """Analyze using OpenAI with JSON mode."""
        client = self._get_openai_client()

        response = await client.chat.completions.create(
            model=self.model if "gpt" in self.model else "gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=2000,
        )

        text = response.choices[0].message.content.strip()
        data = json.loads(text)
        analysis = TenderAnalysis(**data)
        return analysis.model_dump()

    def _fallback_analysis(self, tender_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Keyword-based fallback analysis when AI is unavailable.
        Provides a basic relevance score based on keyword matching.
        """
        from config.settings import RELEVANT_KEYWORDS

        text = (
            f"{tender_data.get('title', '')} "
            f"{tender_data.get('description', '')} "
            f"{tender_data.get('organization', '')}"
        ).upper()

        matched = [kw for kw in RELEVANT_KEYWORDS if kw.upper() in text]
        score = min(100, len(matched) * 15)

        return TenderAnalysis(
            relevance_score=score,
            is_relevant=score >= 50,
            key_requirements=[],
            emd_amount=None,
            eligibility_criteria=[],
            scope_of_work="AI analysis unavailable — keyword match only",
            reason=f"Keyword-based analysis: matched {len(matched)} keywords. AI analysis failed.",
            matched_domains=matched,
            recommended_action="Review" if score >= 50 else "Ignore",
        ).model_dump()

    async def analyze_batch(self, tenders: list, pdf_texts: dict | None = None) -> list:
        """
        Analyze multiple tenders sequentially with rate limiting.
        Returns list of (tender_id, analysis_dict) tuples.
        """
        pdf_texts = pdf_texts or {}
        results = []

        for tender in tenders:
            tid = tender.tender_id if hasattr(tender, 'tender_id') else tender.get("tender_id", "")
            tender_dict = tender.to_dict() if hasattr(tender, "to_dict") else tender
            pdf_text = pdf_texts.get(tid, "")

            try:
                analysis = await self.analyze(tender_dict, pdf_text=pdf_text)
                results.append((tid, analysis))
            except Exception as e:
                logger.error("Batch analysis item failed", tender_id=tid, error=str(e))
                fallback = self._fallback_analysis(tender_dict)
                results.append((tid, fallback))

            # Small delay between requests
            await asyncio.sleep(1)

        return results
