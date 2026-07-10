"""
Tests for src/pipeline/agent.py  —  Phase 3
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from src.pipeline.agent import run_agent


def _has_api_key() -> bool:
    from dotenv import load_dotenv
    load_dotenv()
    return bool(os.environ.get("GEMINI_API_KEY", "").strip())


class TestAgentGuards:
    def test_empty_claim_fails_gracefully(self):
        res = run_agent("")
        assert res["success"] is False
        assert res["verdict"] == "Unverifiable"
        assert res["error"] is not None

    def test_missing_api_key_fails(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        res = run_agent("Water freezes at 0C")
        assert res["success"] is False
        assert "GEMINI_API_KEY" in res["error"]


class TestAgentMocked:

    @patch("google.genai.Client")
    def test_agent_run_success_mocked(self, mock_client_class, monkeypatch):
        """Test the agent runner and validation flow offline using mocked Gemini API."""
        monkeypatch.setenv("GEMINI_API_KEY", "mocked_key")

        # 1. Setup mock client and generation response
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        mock_response = MagicMock()
        mock_response.text = (
            '{"verdict": "True", "confidence": 0.95, '
            '"summary": "Verified via USDA data.", '
            '"sources": [{"title": "USDA", "url": "https://gov.com", "tier": 1}]}'
        )
        mock_client.models.generate_content.return_value = mock_response

        # 2. Run agent
        res = run_agent("Water freezes at 0C")

        # 3. Assertions
        assert res["success"] is True
        assert res["verdict"] == "True"
        assert res["confidence"] == 0.95
        assert res["summary"] == "Verified via USDA data."
        assert len(res["sources"]) == 1
        assert res["sources"][0]["title"] == "USDA"
        assert res["sources"][0]["url"] == "https://gov.com"
        assert res["sources"][0]["tier"] == 1

        # Verify correct configuration was passed to the Gemini SDK
        mock_client.models.generate_content.assert_called_once()
        call_kwargs = mock_client.models.generate_content.call_args[1]
        assert call_kwargs["model"] == "gemini-3.1-flash-lite"
        
        # Check that the tool was registered
        registered_tools = call_kwargs["config"].tools
        assert len(registered_tools) == 1
        assert registered_tools[0].__name__ == "search_web_evidence"


@pytest.mark.slow
class TestAgentExecution:

    @pytest.fixture(autouse=True)
    def require_api_key_and_live_flag(self):
        if not _has_api_key():
            pytest.skip("GEMINI_API_KEY not configured — skipping live LLM test")
        if os.environ.get("RUN_LIVE_TESTS") != "1":
            pytest.skip("RUN_LIVE_TESTS is not 1 — skipping slow live LLM test to prevent rate-limits")

    @patch("src.pipeline.agent.verify_claim")
    def test_agent_loop_success(self, mock_verify):
        """Verify the agent plans, runs the web search tool, and synthesizes the verdict."""
        # 1. Setup mock search output (forces True verdict)
        mock_verify.return_value = {
            "success": True,
            "evidence": [
                {
                    "source_url": "https://www.nist.gov/water-freezing-point",
                    "title": "NIST Water Phase Data",
                    "snippet": "Pure water freezes at exactly 0 degrees Celsius under standard atmospheric pressure.",
                    "authority_score": 0.95,
                    "authority_tier": 1,
                    "query": "water freezing point"
                }
            ],
            "workspace_discussions": []
        }

        # 2. Run agent on a simple claim
        claim = "Water freezes at 0 degrees Celsius under standard atmospheric pressure."
        res = run_agent(claim)

        # 3. Assertions
        assert res["success"] is True, f"Agent run failed: {res['error']}"
        assert res["verdict"] == "True"
        assert res["confidence"] >= 0.8
        assert len(res["sources"]) >= 1
        assert res["sources"][0]["url"] == "https://www.nist.gov/water-freezing-point"
        assert res["sources"][0]["tier"] == 1

        # Verify that the search tool was indeed called by the agent loop
        mock_verify.assert_called()
