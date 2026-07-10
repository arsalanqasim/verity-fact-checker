"""
Stage 3 & 4 — Autonomous Agentic Search & Synthesis Loop

Responsibility:
  Coordinates the autonomous fact-checking loop. Gives Gemini access to
  Brave Search MCP as a tool, allowing the agent to formulate queries,
  evaluate results, refine its strategy, and synthesize a structured verdict.
"""

from __future__ import annotations

import logging
import os
from typing import Literal, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src.pipeline.verification import verify_claim

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured Output Schema
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
        description="List of sources from the search results that were actually used to synthesize this verdict."
    )

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def search_web_evidence(query: str) -> str:
    """
    Search the web for evidence to verify a factual claim.
    
    Parameters:
        query: The search query to run on the web search engine.
        
    Returns:
        A formatted string of evidence snippets annotated with source authority scores and tiers.
    """
    logger.info(f"[Agent Tool Execution] Running Brave Search for: '{query}'")
    # Execute verification search using verify_claim
    res = verify_claim(query, claim_type="single_fact")
    if not res.get("success"):
        return f"Search error: {res.get('error', 'unknown error')}"
        
    evidence = res.get("evidence", [])
    if not evidence:
        return f"No search results found for query: '{query}'."
        
    formatted = []
    for idx, item in enumerate(evidence, start=1):
        formatted.append(
            f"Evidence [{idx}]:\n"
            f"  Title: {item.get('title')}\n"
            f"  URL: {item.get('source_url')}\n"
            f"  Tier: {item.get('authority_tier')}\n"
            f"  Score: {item.get('authority_score'):.2f}\n"
            f"  Snippet: {item.get('snippet')}\n"
        )
    return "\n".join(formatted)

# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert, autonomous fact-checking agent. Your goal is to evaluate if a target claim is True, False, Misleading, or Unverifiable.

You have access to the tool `search_web_evidence` to query the web.

Instructions:
1. Formulate a search plan. Decide what queries are needed to find authoritative evidence.
2. Call `search_web_evidence` with your query.
3. Review the returned evidence snippets. Note their authority tiers:
   - Tier 1 (.gov, .edu, journals, PubMed, USDA) is highly trusted.
   - Tier 2 (established news wires, reputable news outlets, specialized fact-checkers) is moderately trusted.
   - Tier 3 (blogs, general web, social media, forums) is low trust.
4. If the initial search results are insufficient, too narrow, or contradictory, refine your search strategy and call the tool again (up to 3 times max). For example, if a comparative claim compares multiple items, run queries for each item.
5. Once you have gathered sufficient evidence, synthesize the final verdict:
   - True: The claim is fully supported by Tier-1 or Tier-2 evidence with no significant caveats.
   - False: The claim is directly contradicted by Tier-1 or Tier-2 evidence.
   - Misleading: The claim contains some truth but leaves out critical context, exaggerates, or misrepresents facts.
   - Unverifiable: There is not enough reliable Tier-1 or Tier-2 evidence to confirm or deny the claim, or the evidence is heavily contradictory/inconclusive.
6. Enforce "Unverifiable" if there is no Tier-1 or Tier-2 evidence available at all.
7. Populate the sources list with the actual titles and URLs of the pages you used from the search results, mapping them to their correct Tier (1, 2, or 3).

Your final output must conform to the required JSON schema.
"""

# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------

_MODEL = "gemini-3.1-flash-lite"

def run_agent(claim: str) -> dict:
    """
    Run the autonomous fact-checking agent on a claim.
    
    Parameters:
        claim: The factual claim statement.
        
    Returns:
        dict containing verdict, confidence, summary, sources, success, and error.
    """
    if not claim or not claim.strip():
        return {
            "verdict": "Unverifiable",
            "confidence": 0.0,
            "summary": "No claim provided.",
            "sources": [],
            "success": False,
            "error": "Claim string was empty."
        }

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return {
            "verdict": "Unverifiable",
            "confidence": 0.0,
            "summary": "Gemini API key is not configured.",
            "sources": [],
            "success": False,
            "error": "GEMINI_API_KEY is not set in the environment."
        }

    logger.info(f"Running autonomous fact-checking agent for claim: '{claim}'")

    prompt = (
        f"{_SYSTEM_PROMPT}\n\n"
        f"Claim to evaluate: {claim}\n"
    )

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model=_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[search_web_evidence],
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
                "summary": "Empty response from agent model.",
                "sources": [],
                "success": False,
                "error": "Gemini returned an empty response."
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
            "error": None
        }

    except Exception as exc:
        logger.error(f"Agent execution failed: {exc}", exc_info=True)
        return {
            "verdict": "Unverifiable",
            "confidence": 0.0,
            "summary": "Failed to synthesize verdict due to an error.",
            "sources": [],
            "success": False,
            "error": f"Agent API error: {exc}"
        }
