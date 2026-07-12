"""
Tests for the forced-synthesis fallback path of the autonomous agent.
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.pipeline.agent import run_agent


class TestAgentFallback:

    @patch("google.genai.Client")
    def test_forced_synthesis_fallback(self, mock_client_class, monkeypatch):
        """
        Verify that the agentic loop handles reaching the iteration cap (4 turns)
        and gracefully falls back to a 5th structured-synthesis turn with tools omitted
        and JSON schema enforced, returning a parsed verdict successfully.
        """
        monkeypatch.setenv("GEMINI_API_KEY", "mocked_key")

        # Create the client and generation responses
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Mock function calls
        mock_function_call = MagicMock()
        mock_function_call.name = "search_web_evidence"
        mock_function_call.args = {"query": "test query"}

        # Candidate content containing the function call
        mock_candidate_content = MagicMock()
        mock_candidate_content.role = "model"
        
        # Turn 1-4 returns function call responses
        mock_response_1 = MagicMock()
        mock_response_1.function_calls = [mock_function_call]
        mock_response_1.candidates = [MagicMock(content=mock_candidate_content)]
        
        # Turn 5 (fallback turn) returns final verdict JSON
        mock_response_final = MagicMock()
        mock_response_final.function_calls = []
        mock_response_final.candidates = [MagicMock(content=mock_candidate_content)]
        mock_response_final.text = (
            '{"verdict": "True", "confidence": 0.85, '
            '"summary": "Fallback synthesis succeeded.", '
            '"sources": [{"title": "Science Journal", "url": "https://science.org", "tier": 1}]}'
        )

        # Set up side_effect to return 4 tool call responses, then the final verdict
        mock_client.models.generate_content.side_effect = [
            mock_response_1,      # Turn 1
            mock_response_1,      # Turn 2
            mock_response_1,      # Turn 3
            mock_response_1,      # Turn 4
            mock_response_final,  # Turn 5 (Fallback Synthesis)
        ]

        # Patch search_web_evidence to avoid real MCP call
        with patch("src.pipeline.agent.search_web_evidence") as mock_search:
            mock_search.return_value = "Mock evidence snippet."

            res = run_agent("Water freezes at 0 degrees Celsius")

        # Verify loop executed exactly 5 generate_content calls (4 loop turns + 1 fallback turn)
        assert mock_client.models.generate_content.call_count == 5

        # Check that the 5th call (fallback turn) did NOT have the 'tools' parameter
        call_args_list = mock_client.models.generate_content.call_args_list
        final_call_kwargs = call_args_list[-1][1]
        final_config = final_call_kwargs["config"]
        
        # Verify tools is not defined or is None
        assert not hasattr(final_config, "tools") or final_config.tools is None
        
        # Verify JSON schema is present on the final call
        assert final_config.response_mime_type == "application/json"
        assert final_config.response_schema is not None

        # Verify result is parsed correctly
        assert res["success"] is True
        assert res["verdict"] == "True"
        assert res["confidence"] == 0.85
        assert "Fallback synthesis succeeded." in res["summary"]
