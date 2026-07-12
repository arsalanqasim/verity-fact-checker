"""
Tests for src/pipeline/reporting.py  —  Phase 4
"""

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.pipeline.reporting import create_fact_check_canvas, add_claim_to_list


class TestCanvasReporting:

    def setup_method(self):
        from src.pipeline.reporting import _workspace_identity_cache
        _workspace_identity_cache.clear()

    def test_create_fact_check_canvas_success(self):
        mock_client = MagicMock()
        mock_client.auth_test.return_value = {
            "ok": True,
            "url": "https://verity-fact-checker.slack.com/",
            "team_id": "T12345678",
        }
        mock_client.canvases_create.return_value = {
            "ok": True,
            "canvas_id": "CAN12345"
        }

        claim = "Bananas are radioactive."
        agent_res = {
            "verdict": "Misleading",
            "confidence": 0.6,
            "summary": "Mild radiation, but harmless.",
            "sources": [{"title": "EPA", "url": "https://epa.gov", "tier": 1}]
        }

        url = create_fact_check_canvas(mock_client, claim, agent_res)
        assert url == "https://verity-fact-checker.slack.com/docs/T12345678/CAN12345"
        
        # Verify API parameters
        mock_client.canvases_create.assert_called_once()
        call_kwargs = mock_client.canvases_create.call_args[1]
        assert call_kwargs["title"] == "Verity Report: Bananas are radioactive."
        assert call_kwargs["document_content"]["type"] == "markdown"
        assert "# ⚖️ Verity Fact-Check Report" in call_kwargs["document_content"]["markdown"]
        assert "MISLEADING" in call_kwargs["document_content"]["markdown"]
        assert "EPA" in call_kwargs["document_content"]["markdown"]

    def test_create_fact_check_canvas_failure(self):
        mock_client = MagicMock()
        mock_client.canvases_create.side_effect = Exception("Slack API rate limit")

        claim = "Bananas are radioactive."
        agent_res = {"verdict": "Misleading"}

        url = create_fact_check_canvas(mock_client, claim, agent_res)
        assert url is None

    def test_create_fact_check_canvas_permission_skipped(self):
        from slack_sdk.errors import SlackApiError
        mock_client = MagicMock()
        
        # Setup mock SlackApiError response
        mock_response = MagicMock()
        mock_response.get.side_effect = lambda k, default=None: {"error": "missing_scope", "needed": "canvases:write"}.get(k, default)
        exc = SlackApiError("Slack API Error", mock_response)
        mock_client.canvases_create.side_effect = exc

        claim = "Bananas are radioactive."
        agent_res = {"verdict": "Misleading"}

        url = create_fact_check_canvas(mock_client, claim, agent_res)
        assert url is None

    def test_create_fact_check_canvas_unexpected_slack_error(self):
        from slack_sdk.errors import SlackApiError
        mock_client = MagicMock()
        
        # Setup mock SlackApiError response for some other error code
        mock_response = MagicMock()
        mock_response.get.side_effect = lambda k, default=None: {"error": "fatal_error"}.get(k, default)
        exc = SlackApiError("Slack API Error", mock_response)
        mock_client.canvases_create.side_effect = exc

        claim = "Bananas are radioactive."
        agent_res = {"verdict": "Misleading"}

        url = create_fact_check_canvas(mock_client, claim, agent_res)
        assert url is None

    def test_create_fact_check_canvas_with_sharing(self):
        mock_client = MagicMock()
        mock_client.auth_test.return_value = {
            "ok": True,
            "url": "https://verity-fact-checker.slack.com/",
            "team_id": "T12345678",
        }
        mock_client.canvases_create.return_value = {
            "ok": True,
            "canvas_id": "CAN12345"
        }

        claim = "Bananas are radioactive."
        agent_res = {"verdict": "Misleading"}

        url = create_fact_check_canvas(
            mock_client,
            claim,
            agent_res,
            channel_id="C987654",
            user_id="U123456"
        )
        assert url == "https://verity-fact-checker.slack.com/docs/T12345678/CAN12345"

        # Verify api_call was called to set permissions
        assert mock_client.api_call.call_count == 2
        calls = mock_client.api_call.call_args_list
        
        # Verify call to grant access to channel
        assert calls[0][0][0] == "canvases.access.set"
        assert calls[0][1]["json"] == {
            "canvas_id": "CAN12345",
            "access_level": "read",
            "channel_ids": ["C987654"]
        }

        # Verify call to grant access to user
        assert calls[1][0][0] == "canvases.access.set"
        assert calls[1][1]["json"] == {
            "canvas_id": "CAN12345",
            "access_level": "read",
            "user_ids": ["U123456"]
        }



class TestListsLogging:

    def test_add_claim_to_list_missing_id_returns_false(self, monkeypatch):
        monkeypatch.delenv("SLACK_LIST_ID", raising=False)
        mock_client = MagicMock()

        claim = "Bananas are radioactive."
        agent_res = {"verdict": "Misleading"}

        res = add_claim_to_list(mock_client, claim, agent_res)
        assert res is False
        mock_client.slackLists_items_create.assert_not_called()

    def test_add_claim_to_list_success(self, monkeypatch):
        # 1. Setup env variables
        monkeypatch.setenv("SLACK_LIST_ID", "L999")
        monkeypatch.setenv("SLACK_LIST_COL_CLAIM", "C_CLAIM")
        monkeypatch.setenv("SLACK_LIST_COL_VERDICT", "C_VERDICT")
        monkeypatch.setenv("SLACK_LIST_COL_CONFIDENCE", "C_CONFIDENCE")
        monkeypatch.setenv("SLACK_LIST_COL_SUMMARY", "C_SUMMARY")

        # 2. Setup mock client
        mock_client = MagicMock()
        mock_client.slackLists_items_create.return_value = {
            "ok": True,
            "id": "item_123"
        }

        claim = "Bananas are radioactive."
        agent_res = {
            "verdict": "Misleading",
            "confidence": 0.6,
            "summary": "Mild radiation, but harmless."
        }

        # 3. Execute
        res = add_claim_to_list(mock_client, claim, agent_res)
        assert res is True

        # 4. Verify arguments
        mock_client.slackLists_items_create.assert_called_once()
        call_kwargs = mock_client.slackLists_items_create.call_args[1]
        assert call_kwargs["list_id"] == "L999"
        
        fields = call_kwargs["initial_fields"]
        assert len(fields) == 4

        # Helper to extract the rendered text from a rich_text field dict
        def _extract_text(field):
            rt = field["rich_text"]
            elements = rt[0]["elements"]
            return "".join(e["text"] for e in elements[0]["elements"])

        claim_field = next(f for f in fields if f["column_id"] == "C_CLAIM")
        assert _extract_text(claim_field) == "Bananas are radioactive."
        verdict_field = next(f for f in fields if f["column_id"] == "C_VERDICT")
        assert _extract_text(verdict_field) == "Misleading"
        confidence_field = next(f for f in fields if f["column_id"] == "C_CONFIDENCE")
        assert _extract_text(confidence_field) == "0.60"
        summary_field = next(f for f in fields if f["column_id"] == "C_SUMMARY")
        assert _extract_text(summary_field) == "Mild radiation, but harmless."

        # Also verify no field uses the old "text" key (the rejected shape)
        assert all("text" not in f for f in fields), "Fields must use rich_text, not plain text"

    def test_add_claim_to_list_failure(self, monkeypatch):
        monkeypatch.setenv("SLACK_LIST_ID", "L999")
        monkeypatch.setenv("SLACK_LIST_COL_CLAIM", "C_CLAIM")
        
        mock_client = MagicMock()
        mock_client.slackLists_items_create.side_effect = Exception("Lists access denied")

        claim = "Bananas are radioactive."
        agent_res = {"verdict": "Misleading"}

        res = add_claim_to_list(mock_client, claim, agent_res)
        assert res is False

    def test_add_claim_to_list_permission_skipped(self, monkeypatch):
        monkeypatch.setenv("SLACK_LIST_ID", "L999")
        monkeypatch.setenv("SLACK_LIST_COL_CLAIM", "C_CLAIM")
        from slack_sdk.errors import SlackApiError
        
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.get.side_effect = lambda k, default=None: {"error": "feature_not_enabled", "needed": "lists:write"}.get(k, default)
        exc = SlackApiError("Slack API Error", mock_response)
        mock_client.slackLists_items_create.side_effect = exc

        claim = "Bananas are radioactive."
        agent_res = {"verdict": "Misleading"}

        res = add_claim_to_list(mock_client, claim, agent_res)
        assert res is False

    def test_add_claim_to_list_unexpected_slack_error(self, monkeypatch):
        monkeypatch.setenv("SLACK_LIST_ID", "L999")
        monkeypatch.setenv("SLACK_LIST_COL_CLAIM", "C_CLAIM")
        from slack_sdk.errors import SlackApiError
        
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.get.side_effect = lambda k, default=None: {"error": "rate_limited"}.get(k, default)
        exc = SlackApiError("Slack API Error", mock_response)
        mock_client.slackLists_items_create.side_effect = exc

        claim = "Bananas are radioactive."
        agent_res = {"verdict": "Misleading"}

        res = add_claim_to_list(mock_client, claim, agent_res)
        assert res is False

