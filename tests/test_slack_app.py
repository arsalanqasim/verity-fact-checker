import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from src.slack_app import run_pipeline_and_reply

class TestSlackAppOrchestration:

    @patch("src.slack_app.ingest")
    @patch("src.slack_app.extract_claim")
    @patch("src.slack_app.verify_claim")
    @patch("src.slack_app.synthesise_verdict")
    def test_run_pipeline_short_circuits_on_other(
        self,
        mock_synthesise,
        mock_verify,
        mock_extract,
        mock_ingest
    ):
        # 1. Setup mock returns
        mock_ingest.return_value = {
            "success": True,
            "raw_text": "hello verity"
        }
        mock_extract.return_value = {
            "success": True,
            "claim": "hello verity",
            "claim_type": "other",
            "compared_items": None
        }

        # 2. Setup mock client
        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ok": True, "ts": "12345.67890"}

        # 3. Execute
        run_pipeline_and_reply(
            text="hello verity",
            channel="C11111",
            thread_ts="11111.22222",
            client=mock_client
        )

        # 4. Verify short-circuit: verify_claim & synthesise_verdict MUST NOT be called
        mock_verify.assert_not_called()
        mock_synthesise.assert_not_called()

        # 5. Verify final update called with guidance blocks
        # First call is postMessage (analyzing)
        # Second call is chat_update (ingesting)
        # Third call is chat_update (extracting claim)
        # Fourth call is chat_update (guidance message)
        assert mock_client.chat_update.call_count == 3
        
        last_update_kwargs = mock_client.chat_update.call_args[1]
        assert last_update_kwargs["channel"] == "C11111"
        assert last_update_kwargs["ts"] == "12345.67890"
        assert last_update_kwargs["text"] == "ℹ️ Verity Guidance"
        
        blocks = last_update_kwargs["blocks"]
        assert len(blocks) > 0
        assert blocks[0]["text"]["text"] == "ℹ️ Verity Guidance"
        assert "I couldn't find a specific factual claim to check in that message." in blocks[1]["text"]["text"]
        assert "hello verity" in blocks[2]["text"]["text"]
        assert "Tip:" in blocks[3]["elements"][0]["text"]

    @patch("src.slack_app.ingest")
    @patch("src.slack_app.extract_claim")
    @patch("src.slack_app.verify_claim")
    @patch("src.slack_app.synthesise_verdict")
    def test_run_pipeline_runs_fully_on_factual_claim(
        self,
        mock_synthesise,
        mock_verify,
        mock_extract,
        mock_ingest
    ):
        # 1. Setup mock returns
        mock_ingest.return_value = {
            "success": True,
            "raw_text": "Lentils have more protein than eggs."
        }
        mock_extract.return_value = {
            "success": True,
            "claim": "Lentils have more protein than eggs.",
            "claim_type": "comparative",
            "compared_items": ["lentils", "eggs"]
        }
        mock_verify.return_value = {
            "success": True,
            "evidence": [{"source_url": "https://gov.com", "title": "USDA", "snippet": "protein content", "authority_score": 0.9, "authority_tier": 1, "query": "lentils"}],
            "workspace_discussions": []
        }
        mock_synthesise.return_value = {
            "success": True,
            "verdict": "True",
            "confidence": 0.95,
            "summary": "Nutritional data verifies protein content.",
            "sources": [{"title": "USDA", "url": "https://gov.com", "tier": 1}]
        }

        # 2. Setup mock client
        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ok": True, "ts": "12345.67890"}

        # 3. Execute
        run_pipeline_and_reply(
            text="Lentils have more protein than eggs.",
            channel="C11111",
            thread_ts="11111.22222",
            client=mock_client
        )

        # 4. Verify all pipeline stages were called
        mock_ingest.assert_called_once_with("Lentils have more protein than eggs.")
        mock_extract.assert_called_once_with("Lentils have more protein than eggs.")
        mock_verify.assert_called_once_with("Lentils have more protein than eggs.", "comparative", ["lentils", "eggs"])
        mock_synthesise.assert_called_once()

        # 5. Verify final update called with verdict blocks
        assert mock_client.chat_update.call_count == 5  # ingesting, extracting, searching, synthesizing, final verdict
        last_update_kwargs = mock_client.chat_update.call_args[1]
        assert last_update_kwargs["channel"] == "C11111"
        assert last_update_kwargs["ts"] == "12345.67890"
        assert "Verity Verdict: True" in last_update_kwargs["text"]
        
        blocks = last_update_kwargs["blocks"]
        assert len(blocks) > 0
        assert blocks[0]["text"]["text"] == "⚖️ Verity Fact Check"
