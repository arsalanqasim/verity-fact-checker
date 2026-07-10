"""
Tests for src/pipeline/verdict.py  —  Phase 4

All tests that call the Gemini API are marked @pytest.mark.slow (require
GEMINI_API_KEY in the environment).

Test matrix:
  No-API tests (always run):
    test_empty_claim_fails_gracefully
    test_missing_api_key_fails

  API tests (require GEMINI_API_KEY):
    test_true_verdict              — strong Tier-1 evidence supporting the claim
    test_false_verdict             — strong Tier-1 evidence contradicting the claim
    test_misleading_verdict        — evidence shows claim is partially true but leaves out critical context
    test_unverifiable_no_tier1     — only Tier-3 evidence is available (must force Unverifiable)
    test_output_schema             — verify all required fields are present
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from src.pipeline.verdict import synthesise_verdict

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_api_key() -> bool:
    from dotenv import load_dotenv
    load_dotenv()
    return bool(os.environ.get("GEMINI_API_KEY", "").strip())


# ---------------------------------------------------------------------------
# No-API tests
# ---------------------------------------------------------------------------

class TestGuards:
    def test_empty_claim_fails_gracefully(self):
        result = synthesise_verdict("", [])
        assert result["success"] is False
        assert result["verdict"] == "Unverifiable"
        assert result["error"] is not None

    def test_missing_api_key_fails(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        result = synthesise_verdict("Claim", [{"source_url": "http://gov", "title": "gov", "snippet": "yes", "authority_tier": 1}])
        assert result["success"] is False
        assert result["verdict"] == "Unverifiable"
        assert "GEMINI_API_KEY" in result["error"]


# ---------------------------------------------------------------------------
# API tests
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestVerdictSynthesis:

    @pytest.fixture(autouse=True)
    def require_api_key(self):
        if not _has_api_key():
            pytest.skip("GEMINI_API_KEY not set — skipping live Gemini tests")

    def test_true_verdict(self):
        claim = "Water freezes at 0 degrees Celsius under standard atmospheric pressure."
        evidence = [
            {
                "source_url": "https://www.nist.gov/water-freezing-point",
                "title": "NIST Water Phase Data",
                "snippet": "At standard atmospheric pressure, pure liquid water undergoes a phase transition to ice at exactly 0 degrees Celsius.",
                "authority_score": 0.95,
                "authority_tier": 1,
            }
        ]
        result = synthesise_verdict(claim, evidence)
        assert result["success"] is True, f"Synthesis failed: {result['error']}"
        assert result["verdict"] == "True"
        assert result["confidence"] >= 0.8
        assert len(result["sources"]) >= 1
        assert result["sources"][0]["url"] == "https://www.nist.gov/water-freezing-point"

    def test_false_verdict(self):
        claim = "Humans can breathe underwater without any equipment."
        evidence = [
            {
                "source_url": "https://www.nih.gov/human-respiratory-system",
                "title": "NIH Respiratory Health",
                "snippet": "Humans rely on lungs that extract oxygen from the air. Humans do not have gills and cannot extract oxygen from water, making it impossible to breathe underwater without breathing apparatus.",
                "authority_score": 0.95,
                "authority_tier": 1,
            }
        ]
        result = synthesise_verdict(claim, evidence)
        assert result["success"] is True
        assert result["verdict"] == "False"
        assert result["confidence"] >= 0.8

    def test_misleading_verdict(self):
        claim = "Bananas are radioactive and eating them can cause immediate radiation poisoning."
        evidence = [
            {
                "source_url": "https://www.epa.gov/radtown/natural-radioactivity-food",
                "title": "EPA Natural Radioactivity in Food",
                "snippet": "Bananas contain naturally occurring potassium-40, which is radioactive. However, the amount of radiation is extremely small, and a human would need to eat millions of bananas in one sitting to get a lethal dose of radiation.",
                "authority_score": 0.95,
                "authority_tier": 1,
            }
        ]
        result = synthesise_verdict(claim, evidence)
        assert result["success"] is True
        assert result["verdict"] == "Misleading"

    def test_unverifiable_no_tier1_or_tier2(self):
        claim = "The secret recipe of a small local bakery in a remote town includes imported saffron from Mars."
        evidence = [
            {
                "source_url": "https://www.somepersonalblog.com/local-bakery",
                "title": "My Favorite Local Bakery",
                "snippet": "A local rumor says that they import their secret saffron from Mars, but nobody knows for sure.",
                "authority_score": 0.20,
                "authority_tier": 3,
            }
        ]
        result = synthesise_verdict(claim, evidence)
        assert result["success"] is True
        # Must force Unverifiable because no Tier 1 or Tier 2 evidence exists
        assert result["verdict"] == "Unverifiable"

    def test_output_schema(self):
        claim = "Vitamin D is synthesized by the skin when exposed to sunlight."
        evidence = [
            {
                "source_url": "https://ods.od.nih.gov/factsheets/VitaminD/",
                "title": "NIH Vitamin D Fact Sheet",
                "snippet": "Vitamin D is produced endogenously when ultraviolet rays from sunlight strike the skin and trigger vitamin D synthesis.",
                "authority_score": 0.95,
                "authority_tier": 1,
            }
        ]
        result = synthesise_verdict(claim, evidence)
        assert result["success"] is True
        for key in ("verdict", "confidence", "summary", "sources", "success", "error"):
            assert key in result
        assert result["verdict"] in ("True", "False", "Misleading", "Unverifiable")
        assert isinstance(result["confidence"], float)
        assert isinstance(result["summary"], str)
        assert isinstance(result["sources"], list)
