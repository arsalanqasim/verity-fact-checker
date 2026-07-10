"""
Tests for src/pipeline/verification.py  —  Phase 3

Test matrix:
  No-network tests (always run):
    TestAuthorityScoring        — the pitch-able design decision, fully unit-testable
    TestQueryBuilding           — per-item query logic for comparative claims
    TestGuards                  — empty claim / missing env var guards

  Live MCP tests (@pytest.mark.slow, require BRAVE_SEARCH_MCP_URL):
    TestLiveVerification        — protein/chicken/eggs comparative example;
                                  prints actual sources + scores for sanity-check

Run no-network tests only:
    pytest tests/test_verification.py -m "not slow" -v

Run all tests (MCP server must be running at BRAVE_SEARCH_MCP_URL):
    pytest tests/test_verification.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from src.pipeline.verification import (
    verify_claim,
    score_authority,
    _build_queries,
)


# ---------------------------------------------------------------------------
# No-network: Authority scoring
# ---------------------------------------------------------------------------

class TestAuthorityScoring:
    """
    The score_authority() function is the named design decision in the pitch.
    These tests lock in the tier taxonomy so it cannot regress silently.
    """

    # --- Tier 1 ---
    def test_gov_tld_is_tier1(self):
        score, tier = score_authority("https://www.cdc.gov/nutrition/data")
        assert tier == 1
        assert score >= 0.75

    def test_edu_tld_is_tier1(self):
        score, tier = score_authority("https://hsph.harvard.edu/research/protein")
        assert tier == 1
        assert score >= 0.75

    def test_pubmed_is_tier1(self):
        score, tier = score_authority("https://pubmed.ncbi.nlm.nih.gov/12345678/")
        assert tier == 1
        assert score >= 0.75

    def test_nih_is_tier1(self):
        score, tier = score_authority("https://ods.od.nih.gov/factsheets/Protein/")
        assert tier == 1
        assert score >= 0.75

    def test_usda_fooddata_is_tier1(self):
        score, tier = score_authority("https://fdc.nal.usda.gov/fdc-app.html#/food-details/172421")
        assert tier == 1
        assert score >= 0.75

    def test_nature_journal_is_tier1(self):
        score, tier = score_authority("https://www.nature.com/articles/s41586-021-03819-2")
        assert tier == 1
        assert score >= 0.75

    def test_examine_is_tier1(self):
        score, tier = score_authority("https://examine.com/nutrition/protein-requirements/")
        assert tier == 1
        assert score >= 0.75

    # --- Tier 2 ---
    def test_reuters_is_tier2(self):
        score, tier = score_authority("https://www.reuters.com/health/article")
        assert tier == 2
        assert 0.45 <= score < 0.75

    def test_snopes_is_tier2(self):
        score, tier = score_authority("https://www.snopes.com/fact-check/protein-content")
        assert tier == 2
        assert 0.45 <= score < 0.75

    def test_bbc_is_tier2(self):
        score, tier = score_authority("https://www.bbc.co.uk/news/health-12345")
        assert tier == 2
        assert 0.45 <= score < 0.75

    def test_healthline_is_tier2(self):
        score, tier = score_authority("https://www.healthline.com/nutrition/protein-foods")
        assert tier == 2
        assert 0.45 <= score < 0.75

    # --- Tier 3 ---
    def test_generic_blog_is_tier3(self):
        score, tier = score_authority("https://www.somerandomblog.com/protein-myths")
        assert tier == 3
        assert score < 0.45

    def test_reddit_is_tier3(self):
        score, tier = score_authority("https://www.reddit.com/r/nutrition/comments/abc123")
        assert tier == 3
        assert score < 0.45

    def test_empty_url_is_tier3(self):
        score, tier = score_authority("")
        assert tier == 3
        assert score < 0.45

    # --- Tier ordering invariant ---
    def test_tier1_always_outscores_tier2(self):
        gov_score, _ = score_authority("https://www.nih.gov/article")
        news_score, _ = score_authority("https://www.reuters.com/article")
        assert gov_score > news_score

    def test_tier2_always_outscores_tier3(self):
        news_score, _ = score_authority("https://www.bbc.com/article")
        blog_score, _ = score_authority("https://www.randomblog123.com/article")
        assert news_score > blog_score


# ---------------------------------------------------------------------------
# No-network: Query building strategy
# ---------------------------------------------------------------------------

class TestQueryBuilding:

    def test_comparative_generates_one_query_per_item(self):
        """Each compared item MUST get its own dedicated query."""
        queries = _build_queries(
            claim="Lentils have more protein per 100g than chicken breast and eggs",
            claim_type="comparative",
            compared_items=["lentils", "chicken breast", "eggs"],
        )
        labels = [label for _, label in queries]
        assert "lentils" in labels
        assert "chicken breast" in labels
        assert "eggs" in labels

    def test_comparative_also_has_overall_query(self):
        queries = _build_queries(
            claim="X has more Y than Z",
            claim_type="comparative",
            compared_items=["X", "Z"],
        )
        labels = [label for _, label in queries]
        assert "overall" in labels

    def test_single_fact_gets_direct_and_context_queries(self):
        queries = _build_queries(
            claim="The Eiffel Tower is 330m tall",
            claim_type="single_fact",
            compared_items=None,
        )
        labels = [label for _, label in queries]
        assert "direct" in labels
        assert "context" in labels

    def test_comparative_without_items_falls_back_to_direct(self):
        queries = _build_queries(
            claim="X is better than Y",
            claim_type="comparative",
            compared_items=None,  # edge case
        )
        # Should not blow up; falls back to direct/context pair
        assert len(queries) >= 1

    def test_query_strings_are_non_empty(self):
        queries = _build_queries(
            claim="Eating red meat causes cancer",
            claim_type="causal",
            compared_items=None,
        )
        for q, _ in queries:
            assert q.strip() != ""


# ---------------------------------------------------------------------------
# No-network: Guards
# ---------------------------------------------------------------------------

class TestGuards:

    def test_empty_claim_fails_gracefully(self):
        result = verify_claim("", "single_fact")
        assert result["success"] is False
        assert result["evidence"] == []
        assert result["error"] is not None

    def test_missing_mcp_url_returns_clear_error(self, monkeypatch):
        monkeypatch.delenv("BRAVE_SEARCH_MCP_URL", raising=False)
        result = verify_claim("The sky is blue", "single_fact")
        assert result["success"] is False
        assert "BRAVE_SEARCH_MCP_URL" in result["error"]


# ---------------------------------------------------------------------------
# Live MCP tests — require BRAVE_SEARCH_MCP_URL set and server running
# ---------------------------------------------------------------------------

def _has_mcp_url() -> bool:
    from dotenv import load_dotenv
    load_dotenv()
    return bool(os.environ.get("BRAVE_SEARCH_MCP_URL", "").strip())


@pytest.mark.slow
class TestLiveVerification:

    @pytest.fixture(autouse=True)
    def require_mcp(self):
        if not _has_mcp_url():
            pytest.skip("BRAVE_SEARCH_MCP_URL not set — skipping live MCP tests")

    def test_protein_comparative_claim(self, capsys):
        """
        The primary scope-doc example: lentils vs chicken vs eggs.
        Comparative → must generate 3+ separate queries, one per item.
        Prints full evidence list so the team can sanity-check rankings.
        """
        result = verify_claim(
            claim="Lentils have more protein per 100g than chicken breast and eggs",
            claim_type="comparative",
            compared_items=["lentils", "chicken breast", "eggs"],
        )

        # Print full evidence for manual sanity-check (visible with pytest -s)
        print("\n" + "=" * 60)
        print("EVIDENCE — protein comparative claim")
        print("=" * 60)
        for i, ev in enumerate(result["evidence"], 1):
            print(
                f"\n[{i}] Tier {ev['authority_tier']} | Score {ev['authority_score']:.2f} | "
                f"Query: '{ev['query']}'"
            )
            print(f"    URL    : {ev['source_url']}")
            print(f"    Title  : {ev['title']}")
            print(f"    Snippet: {ev['snippet'][:120]}...")
        print("=" * 60)
        print(f"Total evidence items: {len(result['evidence'])}")
        print(f"Success: {result['success']} | Error: {result['error']}")

        assert result["success"] is True, f"verify_claim failed: {result['error']}"
        assert len(result["evidence"]) > 0, "No evidence returned"

        # Evidence must be sorted — highest authority_score first
        scores = [e["authority_score"] for e in result["evidence"]]
        assert scores == sorted(scores, reverse=True), "Evidence not sorted by authority_score"

        # Must have gathered queries for each compared item
        queries_used = {e["query"] for e in result["evidence"]}
        assert "lentils" in queries_used, "No separate query run for 'lentils'"
        assert any("chicken" in q for q in queries_used), "No separate query run for 'chicken'"
        assert "eggs" in queries_used, "No separate query run for 'eggs'"

        # Every result must have required fields
        for ev in result["evidence"]:
            assert "source_url" in ev
            assert "snippet" in ev
            assert "authority_score" in ev
            assert "authority_tier" in ev
            assert ev["authority_tier"] in (1, 2, 3)
            assert 0.0 <= ev["authority_score"] <= 1.0

    def test_single_fact_eiffel_tower(self):
        result = verify_claim(
            claim="The Eiffel Tower is 330 metres tall",
            claim_type="single_fact",
            compared_items=None,
        )
        assert result["success"] is True, f"verify_claim failed: {result['error']}"
        assert len(result["evidence"]) > 0

    def test_result_schema_complete(self):
        result = verify_claim(
            claim="Vitamin C prevents scurvy",
            claim_type="causal",
            compared_items=None,
        )
        assert "evidence" in result
        assert "workspace_discussions" in result
        assert "success" in result
        assert "error" in result
        assert isinstance(result["evidence"], list)
        assert isinstance(result["workspace_discussions"], list)


class TestWorkspaceHistoryGuards:
    def test_search_workspace_history_skipped_when_token_missing(self, monkeypatch):
        # Ensure token is missing
        monkeypatch.delenv("SLACK_USER_TOKEN", raising=False)
        from src.pipeline.verification import search_workspace_history
        res = search_workspace_history("test query")
        assert res == []

    def test_search_workspace_history_success(self, monkeypatch):
        import re
        monkeypatch.setenv("SLACK_USER_TOKEN", "xoxp-mock-user-token")
        
        called_args = []

        class MockWebClient:
            def __init__(self, token):
                assert token == "xoxp-mock-user-token"

            def api_call(self, method, json=None, **kwargs):
                called_args.append((method, json))
                return {
                    "ok": True,
                    "results": {
                        "messages": [
                            {
                                "type": "message",
                                "text": "This is a mock message discussing the claim.",
                                "user": "U12345",
                                "ts": "1672574400.000000",
                                "permalink": "https://slack.com/archives/C12345/p1672574400000000",
                                "channel": {
                                    "id": "C12345",
                                    "name": "general"
                                }
                            }
                        ]
                    }
                }

        monkeypatch.setattr("slack_sdk.WebClient", MockWebClient)

        from src.pipeline.verification import search_workspace_history
        res = search_workspace_history("protein content")
        
        # Verify the API call arguments
        assert len(called_args) == 1
        method, payload = called_args[0]
        assert method == "assistant.search.context"
        assert payload["query"] == "protein content"
        assert payload["content_types"] == ["messages"]
        assert payload["limit"] == 20

        # Verify parsed output
        assert len(res) == 1
        discussion = res[0]
        assert discussion["channel_name"] == "#general"
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", discussion["date"])
        assert discussion["permalink"] == "https://slack.com/archives/C12345/p1672574400000000"
        assert discussion["text"] == "This is a mock message discussing the claim."

    def test_search_workspace_history_api_error(self, monkeypatch):
        monkeypatch.setenv("SLACK_USER_TOKEN", "xoxp-mock-user-token")

        class MockWebClientError:
            def __init__(self, token):
                pass

            def api_call(self, method, json=None, **kwargs):
                return {"ok": False, "error": "ratelimited"}

        monkeypatch.setattr("slack_sdk.WebClient", MockWebClientError)

        from src.pipeline.verification import search_workspace_history
        res = search_workspace_history("protein content")
        assert res == []

    def test_search_workspace_history_exception_graceful(self, monkeypatch):
        monkeypatch.setenv("SLACK_USER_TOKEN", "xoxp-mock-user-token")

        class MockWebClientException:
            def __init__(self, token):
                pass

            def api_call(self, method, json=None, **kwargs):
                raise ValueError("Connection failed")

        monkeypatch.setattr("slack_sdk.WebClient", MockWebClientException)

        from src.pipeline.verification import search_workspace_history
        res = search_workspace_history("protein content")
        assert res == []

