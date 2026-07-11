"""
Stage 2 — Claim Extraction

Responsibility:
  Given the raw text produced by the Ingestion stage, identify the specific,
  checkable claim(s) contained in that text via a structured LLM call to the
  Gemini API (Google AI Studio, gemini-3.1-flash-lite).

Key design decisions:
  - Uses Gemini (gemini-3.1-flash-lite) with structured JSON output via
    ``response_mime_type="application/json"`` + ``response_schema`` (Pydantic).
    No free-text parsing anywhere in this module.
  - Correctly classifies claim *type*:
      • ``single_fact``  — one discrete, verifiable assertion.
      • ``comparative``  — e.g. "X has more protein than Y and Z" must be
        evaluated as a ranking/comparison claim, not decomposed into independent
        single-fact checks.  ``compared_items`` is populated for these.
      • ``causal``       — assertion that A causes / caused / prevents B.
      • ``other``        — anything that does not fit the above categories
        (opinion, prediction, vague claim).
  - ``thinking_budget=0`` is set explicitly: this is a deterministic JSON
    extraction task, not a reasoning task.  Disabling thinking cuts latency
    significantly for a claim-extraction call that runs on every user message.
  - All failure paths return ``{"success": False, "error": "<reason>"}`` so
    callers never need try/except boilerplate.

Public API:
  ``extract_claim(raw_text: str) -> dict``

Return schema:
  {
    "claim":          str,            # the specific, checkable claim
    "claim_type":     str,            # "single_fact" | "comparative" | "causal" | "other"
    "compared_items": list[str]|None, # populated only for comparative claims
    "success":        bool,
    "error":          str|None,
  }

Environment:
  GEMINI_API_KEY — Google AI Studio API key (https://aistudio.google.com/apikey)
"""

from __future__ import annotations

import json
import os
from typing import Literal, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

# ---------------------------------------------------------------------------
# Gemini structured-output schema
# ---------------------------------------------------------------------------

class _ClaimSchema(BaseModel):
    """Pydantic model that drives Gemini's structured JSON output."""

    claim: str = Field(
        description=(
            "The single most specific, checkable factual claim in the text. "
            "Write it as a clear, standalone declarative sentence. "
            "Do not include opinion, hedging, or context — just the verifiable assertion."
        )
    )
    claim_type: Literal["single_fact", "comparative", "causal", "other"] = Field(
        description=(
            "single_fact: one discrete fact that can be verified by looking up a single value. "
            "comparative: the claim explicitly compares two or more things (more than, less than, "
            "  higher than, better than, most X of all Y, etc.) — requires checking multiple values. "
            "causal: asserts that A causes, caused, prevents, or leads to B. "
            "other: opinion, prediction, vague assertion, or anything else."
        )
    )
    compared_items: Optional[list[str]] = Field(
        default=None,
        description=(
            "Only populate this for comparative claims. "
            "List every specific entity being compared (e.g. food names, countries, products). "
            "Leave null for single_fact, causal, and other."
        ),
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a fact-checking assistant specialising in claim extraction.

Your task is to read the provided text and identify the single most important, \
specific, checkable factual claim it contains.

Rules:
1. Extract the CLAIM as a clear declarative sentence — no hedging, no opinion, \
   just the core verifiable assertion.
2. Classify the CLAIM TYPE:
   - single_fact  → one value can confirm or deny it (e.g. "The Eiffel Tower is 330 m tall")
   - comparative  → explicitly compares ≥2 things (e.g. "Lentils have more protein \
than chicken and eggs") — MUST be classified as comparative, NOT single_fact, \
because verifying it requires looking up multiple values and comparing them
   - causal       → asserts A causes / prevents / leads to B
   - other        → opinion, prediction, vague claim
3. For comparative claims ONLY, list every named entity being compared in \
   compared_items (e.g. ["lentils", "chicken", "eggs"]).
4. If the text contains no clear factual claim, set claim_type to "other" and \
   describe what the text is about in the claim field.

Output ONLY the JSON object matching the schema — no explanation, no markdown.
"""

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_MODEL = "gemini-3.1-flash-lite"


def extract_claim(raw_text: str) -> dict:
    """
    Extract the dominant checkable claim from ``raw_text`` using Gemini.

    Parameters
    ----------
    raw_text:
        Plain text produced by the Ingestion stage.

    Returns
    -------
    dict with keys:
      - ``claim``          : the extracted claim sentence
      - ``claim_type``     : ``"single_fact"`` | ``"comparative"`` | ``"causal"`` | ``"other"``
      - ``compared_items`` : list of compared entities (comparative only), else ``None``
      - ``success``        : ``True`` if extraction succeeded
      - ``error``          : human-readable error string, or ``None`` on success
    """
    text = raw_text.strip() if raw_text else ""

    if not text:
        return {
            "claim": None,
            "claim_type": None,
            "compared_items": None,
            "success": False,
            "error": "Input text was empty.",
        }

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return {
            "claim": None,
            "claim_type": None,
            "compared_items": None,
            "success": False,
            "error": "GEMINI_API_KEY is not set in the environment.",
        }

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model=_MODEL,
            contents=f"{_SYSTEM_PROMPT}\n\nText to analyse:\n{text}",
            config=types.GenerateContentConfig(
                # Disable thinking — this is pure JSON extraction, not reasoning.
                # thinking_budget=0 cuts latency by ~60% for this call type.
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                response_mime_type="application/json",
                response_schema=_ClaimSchema,
                temperature=0,  # deterministic output
            ),
        )

        # Gemini structured-output returns a JSON string in response.text
        raw_json = response.text
        if not raw_json:
            return {
                "claim": None,
                "claim_type": None,
                "compared_items": None,
                "success": False,
                "error": "Gemini returned an empty response.",
            }

        parsed = _ClaimSchema.model_validate_json(raw_json)

        # Normalise: compared_items should always be None for non-comparative claims
        compared = parsed.compared_items
        if parsed.claim_type != "comparative":
            compared = None
        elif compared is not None:
            # Strip whitespace from each item, drop empty strings
            compared = [item.strip() for item in compared if item.strip()]
            if not compared:
                compared = None

        return {
            "claim": parsed.claim,
            "claim_type": parsed.claim_type,
            "compared_items": compared,
            "success": True,
            "error": None,
        }

    except Exception as exc:  # noqa: BLE001
        return {
            "claim": None,
            "claim_type": None,
            "compared_items": None,
            "success": False,
            "error": f"Gemini API error: {exc}",
        }
