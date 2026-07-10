"""
Tests for src/pipeline/claims.py  —  Phase 2

All tests that call the Gemini API are marked @pytest.mark.slow (require
GEMINI_API_KEY in the environment).  Run offline-safe tests only with:
    pytest tests/test_claims.py -m "not slow"

Test matrix:
  No-API tests (always run):
    test_empty_input_fails                — guard, no network
    test_missing_api_key_fails            — guard, no network

  API tests (require GEMINI_API_KEY):
    test_protein_comparative_claim        — THE scope-doc example: must be
                                            comparative with correct compared_items
    test_single_fact_eiffel_tower         — archetypal single_fact
    test_causal_claim_detection           — causal classification
    test_other_claim_opinion              — opinion → "other"
    test_youtube_transcript_passthrough   — longer text (simulated transcript)
    test_return_schema_always_complete    — all keys present on success
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from src.pipeline.claims import extract_claim

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_api_key() -> bool:
    from dotenv import load_dotenv
    load_dotenv()
    return bool(os.environ.get("GEMINI_API_KEY", "").strip())


# ---------------------------------------------------------------------------
# No-API guard tests  (always run, zero network)
# ---------------------------------------------------------------------------

class TestGuards:
    def test_empty_input_fails_gracefully(self):
        result = extract_claim("")
        assert result["success"] is False
        assert result["claim"] is None
        assert result["error"] is not None

    def test_whitespace_only_fails_gracefully(self):
        result = extract_claim("   \n\t  ")
        assert result["success"] is False
        assert result["claim"] is None

    def test_missing_api_key_returns_clear_error(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        result = extract_claim("The Earth is 4.5 billion years old.")
        assert result["success"] is False
        assert "GEMINI_API_KEY" in result["error"]


# ---------------------------------------------------------------------------
# API tests  (require GEMINI_API_KEY)
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestClaimExtraction:

    @pytest.fixture(autouse=True)
    def require_api_key(self):
        if not _has_api_key():
            pytest.skip("GEMINI_API_KEY not set — skipping live Gemini tests")

    # ------------------------------------------------------------------
    # THE canonical test from scope_document.md
    # "a user sees an Instagram Reel claiming a specific food has more
    #  protein than any other food, including chicken and eggs"
    # ------------------------------------------------------------------
    def test_protein_comparative_claim(self):
        """
        This is the primary motivating example from scope_document.md.
        It MUST be classified as 'comparative' — not 'single_fact' —
        because verifying it requires looking up and comparing multiple values.
        compared_items must include all three subjects: the food, chicken, eggs.
        """
        text = (
            "Lentils have more protein per 100g than any other food, "
            "including chicken breast and eggs."
        )
        result = extract_claim(text)

        assert result["success"] is True, f"API call failed: {result['error']}"
        assert result["claim_type"] == "comparative", (
            f"Expected 'comparative' but got '{result['claim_type']}'. "
            f"Claim extracted: '{result['claim']}'"
        )
        assert result["compared_items"] is not None, (
            "compared_items must be populated for comparative claims"
        )
        # All three subjects should appear (case-insensitive)
        items_lower = [item.lower() for item in result["compared_items"]]
        assert any("lentil" in i for i in items_lower), (
            f"'lentils' missing from compared_items: {result['compared_items']}"
        )
        assert any("chicken" in i for i in items_lower), (
            f"'chicken' missing from compared_items: {result['compared_items']}"
        )
        assert any("egg" in i for i in items_lower), (
            f"'eggs' missing from compared_items: {result['compared_items']}"
        )

    def test_superlative_is_also_comparative(self):
        """
        Superlative claims ("X is the most Y") are a subclass of comparative
        and must not be misclassified as single_fact.
        """
        text = "Quinoa is the most complete protein source of all plant foods."
        result = extract_claim(text)

        assert result["success"] is True, f"API call failed: {result['error']}"
        assert result["claim_type"] == "comparative", (
            f"Superlative claim was misclassified as '{result['claim_type']}'"
        )

    def test_single_fact_eiffel_tower(self):
        """Archetypal single-fact claim — one value, one lookup."""
        text = "The Eiffel Tower stands 330 metres tall including its antenna."
        result = extract_claim(text)

        assert result["success"] is True, f"API call failed: {result['error']}"
        assert result["claim_type"] == "single_fact", (
            f"Expected 'single_fact' but got '{result['claim_type']}'"
        )
        assert result["compared_items"] is None, (
            "compared_items must be None for single_fact claims"
        )
        assert "eiffel" in result["claim"].lower() or "330" in result["claim"]

    def test_causal_claim_detection(self):
        """Causal claims must be classified as 'causal', not 'single_fact'."""
        text = "Eating red meat more than twice a week causes an increased risk of colorectal cancer."
        result = extract_claim(text)

        assert result["success"] is True, f"API call failed: {result['error']}"
        assert result["claim_type"] == "causal", (
            f"Expected 'causal' but got '{result['claim_type']}'. "
            f"Claim: '{result['claim']}'"
        )
        assert result["compared_items"] is None

    def test_opinion_classified_as_other(self):
        """Pure opinion/prediction with no verifiable fact → 'other'."""
        text = "I think the economy will be much better next year."
        result = extract_claim(text)

        assert result["success"] is True, f"API call failed: {result['error']}"
        assert result["claim_type"] == "other", (
            f"Opinion was classified as '{result['claim_type']}' — expected 'other'"
        )

    def test_longer_transcript_extracts_dominant_claim(self):
        """
        Simulates a YouTube transcript excerpt with filler around a key claim.
        The extractor should pull the dominant checkable claim, not the filler.
        """
        text = (
            "Hey guys, welcome back to the channel! So today I want to talk about "
            "something really interesting I read about. Scientists have actually "
            "proven that drinking two cups of green tea per day reduces the risk of "
            "heart disease by 30 percent. Pretty amazing right? Anyway, don't forget "
            "to hit that like button and subscribe!"
        )
        result = extract_claim(text)

        assert result["success"] is True, f"API call failed: {result['error']}"
        # Should extract the green tea / heart disease claim, not the filler
        assert result["claim"] is not None
        assert len(result["claim"]) > 10
        # Most likely causal, but could be single_fact depending on phrasing —
        # either is acceptable as long as it's not "other"
        assert result["claim_type"] in ("causal", "single_fact", "comparative"), (
            f"Transcript claim was classified as 'other' — likely extracted filler: "
            f"'{result['claim']}'"
        )

    def test_return_schema_always_has_all_keys(self):
        """All four payload keys must be present regardless of claim type."""
        text = "Mount Everest is 8,849 metres above sea level."
        result = extract_claim(text)

        assert result["success"] is True, f"API call failed: {result['error']}"
        for key in ("claim", "claim_type", "compared_items", "success", "error"):
            assert key in result, f"Key '{key}' missing from result dict"

    def test_claim_is_non_empty_string_on_success(self):
        """Claim field must be a non-empty string when success=True."""
        text = "Humans only use 10% of their brain."
        result = extract_claim(text)

        assert result["success"] is True, f"API call failed: {result['error']}"
        assert isinstance(result["claim"], str)
        assert len(result["claim"].strip()) > 0
