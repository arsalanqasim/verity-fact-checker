"""
Stage 4 — Verdict Synthesis

Responsibility:
  Given the weighted evidence bundle from the Verification stage, make a
  final LLM call (Gemini, gemini-3.1-flash-lite) that produces a structured verdict ready for
  Slack delivery.

Key design decisions:
  - Verdict labels are exactly four: True | False | Misleading | Unverifiable.
    No other labels are permitted so downstream Block Kit formatting stays
    deterministic.
  - Output is always structured JSON via Gemini's structured output mode
    (response_mime_type="application/json" with a response_schema).
  - Explicitly instructs the LLM to weight Tier-1 sources (.gov, .edu, journals,
    PubMed, USDA) more heavily than Tier-2 (news wires, established news) and
    Tier-3 (blogs, general web, social media).
  - Explicitly instructs the LLM to label a claim "Unverifiable" when no Tier-1
    or Tier-2 evidence is available, or when the evidence is contradictory/inconclusive.
  - Set thinking_budget=0 to keep latency low for this synthesis call.

Public API:
  ``synthesise_verdict(claim: str, evidence: list[dict]) -> dict``

Return schema:
  {
    "verdict": "True" | "False" | "Misleading" | "Unverifiable",
    "confidence": float,  # 0.0 - 1.0
    "summary": str,  # one-sentence explanation
    "sources": [{"title": str, "url": str, "tier": int}],
    "success": bool,
    "error": str | None
  }
"""

from __future__ import annotations

import os
from typing import Literal, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Structured output schemas
# ---------------------------------------------------------------------------

class _SourceSchema(BaseModel):
    title: str = Field(description="The title of the source page or document.")
    url: str = Field(description="The URL of the source.")
    tier: int = Field(description="The authority tier of the source: 1, 2, or 3.")


class _VerdictSchema(BaseModel):
    verdict: Literal["True", "False", "Misleading", "Unverifiable"] = Field(
        description="The final verdict for the claim. Must be exactly: True, False, Misleading, or Unverifiable."
    )
    confidence: float = Field(
        description="Confidence score for the verdict, between 0.0 and 1.0."
    )
    summary: str = Field(
        description="A concise, one-sentence explanation of the verdict, summarizing the key evidence."
    )
    sources: list[_SourceSchema] = Field(
        description="List of sources used as evidence to synthesize this verdict."
    )


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert fact-checking synthesis agent. Your task is to evaluate a target claim \
against a list of gathered evidence snippets and produce a final structured verdict.

Evaluate the evidence using these strict guidelines:
1. Weight Tiers heavily:
   - Tier 1 (.gov, .edu, peer-reviewed journals, primary databases like PubMed/USDA) is highly trusted.
   - Tier 2 (established news wires, snopes, reputable news outlets) is moderately trusted.
   - Tier 3 (blogs, general web, social media, forums) has low trust.
2. Force "Unverifiable" when:
   - There is NO Tier-1 or Tier-2 evidence available at all.
   - The evidence is heavily contradictory, incomplete, or inconclusive.
   - The sources do not directly address the claim.
3. Select the verdict:
   - True: The claim is fully supported by high-quality (Tier-1 or Tier-2) evidence with no significant caveats.
   - False: The claim is directly contradicted by high-quality evidence.
   - Misleading: The claim contains some truth but leaves out critical context, exaggerates, or misrepresents facts.
   - Unverifiable: There is not enough reliable or high-quality evidence to confirm or deny the claim.
4. Confidence Score:
   - Assign a float between 0.0 and 1.0 representing how certain you are of the verdict given the available evidence quality.
   - High confidence (e.g. >= 0.8) requires strong, consistent Tier-1 or Tier-2 evidence.
   - If evidence is weak or only Tier-3, confidence must be low and the verdict should typically be "Unverifiable".
5. Summary:
   - Provide a clear, objective, one-sentence explanation of the verdict.
6. Sources:
   - Include only the sources from the input evidence that were actually relevant and used in the evaluation.
"""

_MODEL = "gemini-3.1-flash-lite"


def synthesise_verdict(claim: str, evidence: list[dict]) -> dict:
    """
    Synthesise a structured verdict for ``claim`` based on gathered ``evidence`` using Gemini.

    Parameters
    ----------
    claim:
        The target claim string.
    evidence:
        List of evidence dicts returned by Stage 3 (verify_claim). Each dict should contain:
        source_url, title, snippet, authority_score, authority_tier.

    Returns
    -------
    dict with keys:
      - ``verdict``    : "True" | "False" | "Misleading" | "Unverifiable"
      - ``confidence`` : float (0.0 to 1.0)
      - ``summary``    : one-sentence explanation
      - ``sources``    : list of {"title": str, "url": str, "tier": int}
      - ``success``    : True if synthesis succeeded
      - ``error``      : None on success, error message string on failure
    """
    if not claim or not claim.strip():
        return {
            "verdict": "Unverifiable",
            "confidence": 0.0,
            "summary": "No claim provided.",
            "sources": [],
            "success": False,
            "error": "Claim string was empty.",
        }

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return {
            "verdict": "Unverifiable",
            "confidence": 0.0,
            "summary": "Gemini API key is not configured.",
            "sources": [],
            "success": False,
            "error": "GEMINI_API_KEY is not set in the environment.",
        }

    # Format the evidence list for the prompt
    formatted_evidence = []
    for idx, item in enumerate(evidence or [], start=1):
        formatted_evidence.append(
            f"Evidence [{idx}]:\n"
            f"  Title: {item.get('title', 'Unknown')}\n"
            f"  URL: {item.get('source_url', 'Unknown')}\n"
            f"  Tier: {item.get('authority_tier', 3)}\n"
            f"  Score: {item.get('authority_score', 0.1):.2f}\n"
            f"  Snippet: {item.get('snippet', '')}\n"
        )
    evidence_text = "\n".join(formatted_evidence) if formatted_evidence else "No evidence available."

    prompt = (
        f"{_SYSTEM_PROMPT}\n\n"
        f"Claim to evaluate: {claim}\n\n"
        f"Available Evidence:\n{evidence_text}\n"
    )

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model=_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                response_mime_type="application/json",
                response_schema=_VerdictSchema,
                temperature=0,  # deterministic output
            ),
        )

        raw_json = response.text
        if not raw_json:
            return {
                "verdict": "Unverifiable",
                "confidence": 0.0,
                "summary": "Empty response from synthesis model.",
                "sources": [],
                "success": False,
                "error": "Gemini returned an empty response.",
            }

        parsed = _VerdictSchema.model_validate_json(raw_json)

        return {
            "verdict": parsed.verdict,
            "confidence": parsed.confidence,
            "summary": parsed.summary,
            "sources": [
                {"title": s.title, "url": s.url, "tier": s.tier}
                for s in parsed.sources
            ],
            "success": True,
            "error": None,
        }

    except Exception as exc:
        return {
            "verdict": "Unverifiable",
            "confidence": 0.0,
            "summary": "Failed to synthesize verdict due to an error.",
            "sources": [],
            "success": False,
            "error": f"Verdict synthesis API error: {exc}",
        }
