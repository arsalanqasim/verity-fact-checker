import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from src.slack_app import run_pipeline_and_reply, run_pipeline_and_reply_assistant


class TestSlackAppOrchestration:

    @patch("src.slack_app.ingest")
    @patch("src.slack_app.extract_claim")
    @patch("src.slack_app.run_agent")
    def test_run_pipeline_short_circuits_on_other(
        self,
        mock_run_agent,
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

        # 4. Verify short-circuit: run_agent MUST NOT be called
        mock_run_agent.assert_not_called()

        # 5. Verify final update called with guidance blocks
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
    @patch("src.slack_app.run_agent")
    @patch("src.slack_app.search_workspace_history")
    @patch("src.slack_app.create_fact_check_canvas")
    @patch("src.slack_app.add_claim_to_list")
    def test_run_pipeline_runs_fully_on_factual_claim(
        self,
        mock_add_claim_list,
        mock_create_canvas,
        mock_search_workspace,
        mock_run_agent,
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
        mock_run_agent.return_value = {
            "success": True,
            "verdict": "True",
            "confidence": 0.95,
            "summary": "Nutritional data verifies protein content.",
            "sources": [{"title": "USDA", "url": "https://gov.com", "tier": 1}]
        }
        mock_search_workspace.return_value = []
        mock_create_canvas.return_value = "https://slack.com/canvas/C123"

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
        mock_run_agent.assert_called_once_with("Lentils have more protein than eggs.", strict=True)
        mock_search_workspace.assert_called_once_with("Lentils have more protein than eggs.")
        mock_create_canvas.assert_called_once()
        mock_add_claim_list.assert_called_once()

        # 5. Verify final update called with verdict blocks in attachments
        assert mock_client.chat_update.call_count == 4  # ingesting, extracting, gathering/synthesizing, final verdict
        last_update_kwargs = mock_client.chat_update.call_args[1]
        assert last_update_kwargs["channel"] == "C11111"
        assert last_update_kwargs["ts"] == "12345.67890"
        assert "Verity Verdict: True" in last_update_kwargs["text"]
        
        attachments = last_update_kwargs["attachments"]
        assert len(attachments) == 1
        assert attachments[0]["color"] == "#2EB67D"
        blocks = attachments[0]["blocks"]
        assert len(blocks) > 0
        assert blocks[0]["text"]["text"] == "⚖️ Verity Fact Check"

    @patch("src.slack_app.ingest")
    @patch("src.slack_app.extract_claim")
    @patch("src.slack_app.run_agent")
    def test_run_pipeline_assistant_short_circuits_on_other(
        self,
        mock_run_agent,
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

        mock_run_agent.assert_not_called()

        # Verify that setStatus was called to show progress
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
    @patch("src.slack_app.run_agent")
    @patch("src.slack_app.search_workspace_history")
    @patch("src.slack_app.create_fact_check_canvas")
    @patch("src.slack_app.add_claim_to_list")
    def test_run_pipeline_assistant_runs_fully_on_factual_claim(
        self,
        mock_add_claim_list,
        mock_create_canvas,
        mock_search_workspace,
        mock_run_agent,
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
        mock_run_agent.return_value = {
            "success": True,
            "verdict": "True",
            "confidence": 0.95,
            "summary": "Nutritional data verifies protein content.",
            "sources": [{"title": "USDA", "url": "https://gov.com", "tier": 1}]
        }
        mock_search_workspace.return_value = []
        mock_create_canvas.return_value = "https://slack.com/canvas/C123"

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
        mock_run_agent.assert_called_once_with("Lentils have more protein than eggs.", strict=True)
        mock_search_workspace.assert_called_once_with("Lentils have more protein than eggs.")
        mock_create_canvas.assert_called_once()
        mock_add_claim_list.assert_called_once()

        # Verify assistant thread status updates:
        # 1. ingesting, 2. extracting, 3. analyzing/gathering
        assert mock_client.assistant_threads_setStatus.call_count == 3

        # Verify final reply was posted via say with attachments
        mock_say.assert_called_once()
        say_kwargs = mock_say.call_args[1]
        assert "Verity Verdict: True" in say_kwargs["text"]
        attachments = say_kwargs["attachments"]
        assert len(attachments) == 1
        assert attachments[0]["color"] == "#2EB67D"
        assert attachments[0]["blocks"][0]["text"]["text"] == "⚖️ Verity Fact Check"

    def test_handle_app_home_opened(self):
        from src.slack_app import handle_app_home_opened
        
        mock_client = MagicMock()
        event = {"user": "U99999"}
        
        handle_app_home_opened(event, mock_client)
        
        mock_client.views_publish.assert_called_once()
        publish_kwargs = mock_client.views_publish.call_args[1]
        assert publish_kwargs["user_id"] == "U99999"
        assert publish_kwargs["view"]["type"] == "home"
        assert "⚖️ Verity Portal Dashboard" in publish_kwargs["view"]["blocks"][0]["text"]["text"]

    @patch("src.slack_app.ingest")
    @patch("src.slack_app.extract_claim")
    @patch("src.slack_app.run_agent")
    @patch("src.slack_app.search_workspace_history")
    @patch("src.slack_app.create_fact_check_canvas")
    @patch("src.slack_app.add_claim_to_list")
    @patch("threading.Thread")
    def test_handle_check_sample_claim(
        self,
        mock_thread,
        mock_add_claim_list,
        mock_create_canvas,
        mock_search_workspace,
        mock_run_agent,
        mock_extract,
        mock_ingest
    ):
        from src.slack_app import handle_check_sample_claim

        # 1. Setup mock returns
        mock_ingest.return_value = {"success": True, "raw_text": "Lentils protein"}
        mock_extract.return_value = {"success": True, "claim": "Lentils protein", "claim_type": "single_fact", "compared_items": None}
        mock_run_agent.return_value = {
            "success": True,
            "verdict": "True",
            "confidence": 0.9,
            "summary": "verified",
            "sources": []
        }
        mock_search_workspace.return_value = []
        mock_create_canvas.return_value = "https://slack.com/canvas/C123"

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
        mock_run_agent.assert_called_once()
        mock_search_workspace.assert_called_once()
        mock_create_canvas.assert_called_once()
        mock_add_claim_list.assert_called_once()

        # Verify views_update was called with final modal layout
        mock_client.views_update.assert_called_once()
        update_kwargs = mock_client.views_update.call_args[1]
        assert update_kwargs["view_id"] == "V12345"
        assert update_kwargs["view"]["type"] == "modal"


class TestAppInitialization:

    @patch("slack_sdk.WebClient.auth_test")
    def test_create_app_success(self, mock_auth, monkeypatch):
        # 1. Setup fake environment variables to satisfy Bolt App constraints
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake-token")
        monkeypatch.setenv("SLACK_SIGNING_SECRET", "fake-secret")

        # Mock auth.test to return a dummy successful response
        mock_auth.return_value = {"ok": True, "bot_id": "B123"}

        # 2. Import create_app and build app
        from src.slack_app import create_app
        app = create_app()

        # 3. Assert it builds a valid Bolt App instance
        from slack_bolt import App
        assert isinstance(app, App)


class TestShareModalSubmit:

    def test_handle_share_modal_submit_not_in_channel_joins_and_retries(self):
        from src.slack_app import handle_share_modal_submit
        from slack_sdk.errors import SlackApiError
        from unittest.mock import ANY

        mock_ack = MagicMock()
        mock_client = MagicMock()
        
        # Configure chat_postMessage to raise not_in_channel SlackApiError on first call,
        # and succeed on the second call.
        mock_response = MagicMock()
        mock_response.get.side_effect = lambda k, default=None: {"error": "not_in_channel"}.get(k, default)
        exc = SlackApiError("Slack API Error", mock_response)
        
        mock_client.chat_postMessage.side_effect = [exc, {"ok": True}]

        body = {
            "user": {"id": "U12345"},
            "view": {
                "state": {
                    "values": {
                        "select_channel_block": {
                            "selected_channel": {
                                "selected_conversation": "C99999"
                            }
                        },
                        "comment_block": {
                            "comment_input": {
                                "value": "Check this out!"
                            }
                        }
                    }
                },
                "private_metadata": '{"claim": "Lentils have protein", "verdict": "True", "summary": "Lentils are high in protein.", "canvas_url": "https://verity.slack.com/docs/T/CAN"}'
            }
        }

        handle_share_modal_submit(mock_ack, body, mock_client)

        # Verify ack was called
        mock_ack.assert_called_once()
        
        # Verify conversations_join was called to join the channel
        mock_client.conversations_join.assert_called_once_with(channel="C99999")
        
        # Verify chat_postMessage was called twice (first failed, second succeeded after join)
        assert mock_client.chat_postMessage.call_count == 2
        mock_client.chat_postMessage.assert_any_call(
            channel="C99999",
            text="Verity Fact Check Shared: Lentils have protein",
            blocks=ANY
        )

    def test_handle_share_modal_submit_failure_sends_dm(self):
        from src.slack_app import handle_share_modal_submit
        from slack_sdk.errors import SlackApiError
        from unittest.mock import ANY

        mock_ack = MagicMock()
        mock_client = MagicMock()
        
        # chat_postMessage always raises an error
        mock_response = MagicMock()
        mock_response.get.side_effect = lambda k, default=None: {"error": "some_other_error"}.get(k, default)
        exc = SlackApiError("Slack API Error", mock_response)
        
        mock_client.chat_postMessage.side_effect = exc

        body = {
            "user": {"id": "U12345"},
            "view": {
                "state": {
                    "values": {
                        "select_channel_block": {
                            "selected_channel": {
                                "selected_conversation": "C99999"
                            }
                        },
                        "comment_block": {
                            "comment_input": {
                                "value": "Check this out!"
                            }
                        }
                    }
                },
                "private_metadata": '{"claim": "Lentils have protein", "verdict": "True", "summary": "Lentils are high in protein.", "canvas_url": "https://verity.slack.com/docs/T/CAN"}'
            }
        }

        handle_share_modal_submit(mock_ack, body, mock_client)

        # Verify ack was called
        mock_ack.assert_called_once()
        
        # Verify it attempted to send a DM to user U12345 after the error
        mock_client.chat_postMessage.assert_called_with(
            channel="U12345",
            text=ANY
        )


class TestProactiveScanner:

    @patch("src.slack_app.ingest")
    @patch("src.slack_app.extract_claim")
    @patch("src.slack_app.run_agent")
    @patch("src.slack_app.search_workspace_history")
    @patch("src.slack_app.create_fact_check_canvas")
    @patch("threading.Thread")
    def test_handle_message_starts_thread_on_factual_url(
        self,
        mock_thread,
        mock_create_canvas,
        mock_search_workspace,
        mock_run_agent,
        mock_extract,
        mock_ingest
    ):
        from src.slack_app import handle_message
        from unittest.mock import ANY

        mock_client = MagicMock()
        mock_say = MagicMock()

        event = {
            "channel": "C12345",
            "text": "Check this vaccine shedding claim: https://politifact.com/factchecks/123",
            "user": "U12345",
            "ts": "1625000000.0001"
        }

        handle_message(event, mock_client, mock_say)

        # Verify a thread was spawned to run the scan
        mock_thread.assert_called_once()
        thread_target = mock_thread.call_args[1]["target"]

        # Setup mock returns to mock the thread's execution
        mock_ingest.return_value = {"success": True, "raw_text": "Vaccines do not shed"}
        mock_extract.return_value = {"success": True, "claim": "Vaccines do not shed", "claim_type": "single_fact"}
        mock_run_agent.return_value = {
            "success": True,
            "verdict": "False",
            "confidence": 1.0,
            "summary": "Vaccines do not contain live virus and cannot shed.",
            "sources": []
        }
        mock_search_workspace.return_value = []
        mock_create_canvas.return_value = "https://verity.slack.com/docs/T/CAN"

        # Execute the thread target synchronously
        thread_target()

        # Verify agent verification was called
        mock_ingest.assert_called_once_with("https://politifact.com/factchecks/123")
        mock_extract.assert_called_once_with("Vaccines do not shed")
        mock_run_agent.assert_called_once_with("Vaccines do not shed", strict=True)

        # Verify chat_postEphemeral was called because the verdict is False
        mock_client.chat_postEphemeral.assert_called_once()
        post_kwargs = mock_client.chat_postEphemeral.call_args[1]
        assert post_kwargs["channel"] == "C12345"
        assert post_kwargs["user"] == "U12345"
        assert "thread_ts" not in post_kwargs
        assert "verified as *FALSE*" in post_kwargs["attachments"][0]["blocks"][0]["text"]["text"]

    def test_handle_message_ignores_dm(self):
        from src.slack_app import handle_message
        mock_client = MagicMock()
        mock_say = MagicMock()

        event = {
            "channel": "D12345",
            "text": "https://politifact.com/factchecks/123"
        }

        handle_message(event, mock_client, mock_say)
        mock_client.chat_postEphemeral.assert_not_called()


