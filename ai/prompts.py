"""
Prompt templates and Pydantic schemas for AI tender analysis.
Defines the business profile and structured output format.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from config.settings import COMPANY_PROFILE, RELEVANT_KEYWORDS


# ── Structured Output Schema ────────────────────────────────────

class TenderAnalysis(BaseModel):
    """Structured AI analysis result for a single tender."""

    relevance_score: int = Field(
        ge=0, le=100,
        description="Relevance score from 0-100 for the company profile"
    )
    is_relevant: bool = Field(
        description="True if the tender is relevant for an Industrial Automation and Electrical Engineering company"
    )
    key_requirements: List[str] = Field(
        default_factory=list,
        description="List of key technical requirements extracted from the tender"
    )
    emd_amount: Optional[str] = Field(
        default=None,
        description="Earnest Money Deposit (EMD) amount if mentioned, with currency"
    )
    eligibility_criteria: List[str] = Field(
        default_factory=list,
        description="List of eligibility criteria for bidders"
    )
    scope_of_work: str = Field(
        default="",
        description="Concise description of the scope of work"
    )
    reason: str = Field(
        default="",
        description="Detailed reason why this tender received this score"
    )
    matched_domains: List[str] = Field(
        default_factory=list,
        description="Which of the company's domains match this tender"
    )
    recommended_action: str = Field(
        default="",
        description="Recommended action: 'Bid', 'Review', 'Monitor', or 'Ignore'"
    )


# ── System Prompt ────────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are an expert tender analysis AI assistant for an Industrial Automation and Electrical Engineering company.

## Company Profile
{COMPANY_PROFILE}

## Relevant Keywords
{', '.join(RELEVANT_KEYWORDS)}

## Your Task
Analyze the given tender document and provide a structured assessment. You MUST:

1. **Relevance Score (0-100)**: Score how relevant this tender is for the company.
   - 90-100: Perfect match — PLC/SCADA/Automation/Panel work directly mentioned
   - 75-89: Strong match — Related electrical/instrumentation work
   - 50-74: Moderate — Some overlap but not core business
   - 25-49: Weak — Tangentially related
   - 0-24: Not relevant — Unrelated industry/domain

2. **Is Relevant**: True if the tender is actionable for this company (generally score >= 50)

3. **Key Requirements**: Extract specific technical requirements (equipment, standards, certifications)

4. **EMD Amount**: Extract the Earnest Money Deposit if mentioned. Include currency (e.g., "INR 5,00,000")

5. **Eligibility Criteria**: List qualification requirements (turnover, experience, certifications, etc.)

6. **Scope of Work**: Summarize the scope in 2-3 sentences

7. **Reason**: Provide a detailed reason for the relevance score given

8. **Matched Domains**: List which of Kapoor Engineers' domains match this tender

9. **Recommended Action**: One of: 'Bid', 'Review', 'Monitor', or 'Ignore'

Be precise and factual. Do not hallucinate information not present in the tender text.
If information is not available, leave the field empty or as an empty list.
"""


# ── Analysis Prompt Template ────────────────────────────────────

ANALYSIS_PROMPT_TEMPLATE = """Analyze the following tender:

## Tender Information
- **Title**: {title}
- **Organization**: {organization}
- **Tender ID**: {tender_id}
- **Published**: {publish_date}
- **Closing Date**: {closing_date}
- **Source**: {source}

## Tender Description
{description}

{pdf_text_section}

Provide your structured analysis.
"""


def build_analysis_prompt(
    title: str,
    organization: str,
    tender_id: str,
    publish_date: str,
    closing_date: str,
    source: str,
    description: str,
    pdf_text: str = "",
) -> str:
    """Build the analysis prompt for a specific tender."""
    pdf_section = ""
    if pdf_text:
        # Limit PDF text to avoid token limits
        truncated = pdf_text[:8000]
        if len(pdf_text) > 8000:
            truncated += "\n\n[... PDF text truncated ...]"
        pdf_section = f"## Additional PDF Document Content\n{truncated}"

    return ANALYSIS_PROMPT_TEMPLATE.format(
        title=title or "N/A",
        organization=organization or "N/A",
        tender_id=tender_id or "N/A",
        publish_date=publish_date or "N/A",
        closing_date=closing_date or "N/A",
        source=source or "N/A",
        description=description or "N/A",
        pdf_text_section=pdf_section,
    )
