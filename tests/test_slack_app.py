import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from src.slack_app import run_pipeline_and_reply, run_pipeline_and_reply_assistant


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

    @patch("src.slack_app.ingest")
    @patch("src.slack_app.extract_claim")
    @patch("src.slack_app.verify_claim")
    @patch("src.slack_app.synthesise_verdict")
    def test_run_pipeline_assistant_short_circuits_on_other(
        self,
        mock_synthesise,
        mock_verify,
        mock_extract,
        mock_ingest
    ):
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

        mock_client = MagicMock()
        mock_say = MagicMock()

        run_pipeline_and_reply_assistant(
            text="hello verity",
            channel="C11111",
            thread_ts="11111.22222",
            client=mock_client,
            say=mock_say
        )

        mock_verify.assert_not_called()
        mock_synthesise.assert_not_called()

        # Verify that setStatus was called to show progress
        # First call: ingesting
        # Second call: extracting
        assert mock_client.assistant_threads_setStatus.call_count == 2
        mock_client.assistant_threads_setStatus.assert_any_call(
            channel_id="C11111", thread_ts="11111.22222", status="ingesting content..."
        )

        # Verify say was called with guidance blocks
        mock_say.assert_called_once()
        say_kwargs = mock_say.call_args[1]
        assert say_kwargs["text"] == "ℹ️ Verity Guidance"
        assert len(say_kwargs["blocks"]) > 0

    @patch("src.slack_app.ingest")
    @patch("src.slack_app.extract_claim")
    @patch("src.slack_app.verify_claim")
    @patch("src.slack_app.synthesise_verdict")
    def test_run_pipeline_assistant_runs_fully_on_factual_claim(
        self,
        mock_synthesise,
        mock_verify,
        mock_extract,
        mock_ingest
    ):
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

        mock_client = MagicMock()
        mock_say = MagicMock()

        run_pipeline_and_reply_assistant(
            text="Lentils have more protein than eggs.",
            channel="C11111",
            thread_ts="11111.22222",
            client=mock_client,
            say=mock_say
        )

        mock_ingest.assert_called_once_with("Lentils have more protein than eggs.")
        mock_extract.assert_called_once_with("Lentils have more protein than eggs.")
        mock_verify.assert_called_once_with("Lentils have more protein than eggs.", "comparative", ["lentils", "eggs"])
        mock_synthesise.assert_called_once()

        # Verify assistant thread status updates:
        # 1. ingesting, 2. extracting, 3. searching, 4. synthesizing
        assert mock_client.assistant_threads_setStatus.call_count == 4

        # Verify final reply was posted via say
        mock_say.assert_called_once()
        say_kwargs = mock_say.call_args[1]
        assert "Verity Verdict: True" in say_kwargs["text"]
        assert say_kwargs["blocks"][0]["text"]["text"] == "⚖️ Verity Fact Check"

    def test_handle_app_home_opened(self):
        from src.slack_app import handle_app_home_opened
        
        mock_client = MagicMock()
        event = {"user": "U99999"}
        
        handle_app_home_opened(event, mock_client)
        
        mock_client.views_publish.assert_called_once()
        publish_kwargs = mock_client.views_publish.call_args[1]
        assert publish_kwargs["user_id"] == "U99999"
        assert publish_kwargs["view"]["type"] == "home"
        assert "⚖️ Verity Fact-Checking Hub" in publish_kwargs["view"]["blocks"][0]["text"]["text"]

    @patch("src.slack_app.ingest")
    @patch("src.slack_app.extract_claim")
    @patch("src.slack_app.verify_claim")
    @patch("src.slack_app.synthesise_verdict")
    @patch("threading.Thread")
    def test_handle_check_sample_claim(
        self,
        mock_thread,
        mock_synthesise,
        mock_verify,
        mock_extract,
        mock_ingest
    ):
        from src.slack_app import handle_check_sample_claim

        # 1. Setup mock returns
        mock_ingest.return_value = {"success": True, "raw_text": "Lentils protein"}
        mock_extract.return_value = {"success": True, "claim": "Lentils protein", "claim_type": "single_fact", "compared_items": None}
        mock_verify.return_value = {"success": True, "evidence": [], "workspace_discussions": []}
        mock_synthesise.return_value = {
            "success": True,
            "verdict": "True",
            "confidence": 0.9,
            "summary": "verified",
            "sources": []
        }

        # 2. Setup mock client
        mock_client = MagicMock()
        mock_client.views_open.return_value = {"ok": True, "view": {"id": "V12345"}}

        body = {
            "trigger_id": "T12345",
            "actions": [{"value": "Lentils have more protein than eggs."}]
        }
        mock_ack = MagicMock()

        # Execute the action handler
        handle_check_sample_claim(mock_ack, body, mock_client)

        # Verify acknowledgment and views_open
        mock_ack.assert_called_once()
        mock_client.views_open.assert_called_once()
        open_kwargs = mock_client.views_open.call_args[1]
        assert open_kwargs["trigger_id"] == "T12345"
        assert open_kwargs["view"]["type"] == "modal"

        # Verify thread was started
        mock_thread.assert_called_once()
        thread_target = mock_thread.call_args[1]["target"]
        
        # Run the thread target function synchronously
        thread_target()

        # Verify pipeline execution
        mock_ingest.assert_called_once()
        mock_extract.assert_called_once()
        mock_verify.assert_called_once()
        mock_synthesise.assert_called_once()

        # Verify views_update was called with final modal layout
        mock_client.views_update.assert_called_once()
        update_kwargs = mock_client.views_update.call_args[1]
        assert update_kwargs["view_id"] == "V12345"
        assert update_kwargs["view"]["type"] == "modal"


