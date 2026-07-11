"""
Tests for src/pipeline/reporting.py  —  Phase 4
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.pipeline.reporting import create_fact_check_canvas, add_claim_to_list


class TestCanvasReporting:

    def test_create_fact_check_canvas_success(self):
        mock_client = MagicMock()
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
        assert url == "https://slack.com/canvas/CAN12345"
        
        # Verify API parameters
        mock_client.canvases_create.assert_called_once()
        call_kwargs = mock_client.canvases_create.call_args[1]
        assert call_kwargs["title"] == "Verity Report: Bananas are radioactive."
        assert call_kwargs["document_content"]["type"] == "markdown"
        assert "# ⚖️ Verity Fact-Check Report" in call_kwargs["document_content"]["markdown"]
        assert "Misleading" in call_kwargs["document_content"]["markdown"]
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
        assert {"column_id": "C_CLAIM", "text": "Bananas are radioactive."} in fields
        assert {"column_id": "C_VERDICT", "text": "Misleading"} in fields
        assert {"column_id": "C_CONFIDENCE", "text": "0.60"} in fields
        assert {"column_id": "C_SUMMARY", "text": "Mild radiation, but harmless."} in fields

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

