"""
Tests for src/pipeline/ingestion.py  —  Phase 1

These tests use REAL network calls intentionally — the goal is to verify that
the pipeline actually works against live services, not just that our code
calls the right functions.  Mark slow tests with ``pytest -m "not slow"`` to
skip network-dependent ones locally when offline.

Test matrix:
  test_plain_text_passthrough        — no network, deterministic
  test_empty_input_fails             — no network, deterministic
  test_plain_text_with_url_fragment  — no network, edge case
  test_instagram_oos_error           — no network, routing guard
  test_tiktok_oos_error              — no network, routing guard
  test_youtube_valid_transcript      — NETWORK: known video with captions
  test_youtube_invalid_id            — NETWORK: non-existent video ID
  test_article_wikipedia             — NETWORK: reliable public article
  test_article_unreachable_url       — NETWORK: bad domain, graceful fail
"""

import sys
import os

# Ensure src/ is importable when running pytest from the repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from src.pipeline.ingestion import ingest


# ===========================================================================
# No-network tests  (always run)
# ===========================================================================

class TestPlainText:
    def test_passthrough_returns_same_string(self):
        claim = "Lentils have more protein per gram than chicken breast."
        result = ingest(claim)
        assert result["source_type"] == "text"
        assert result["success"] is True
        assert result["raw_text"] == claim
        assert result["error"] is None

    def test_leading_trailing_whitespace_stripped(self):
        claim = "  The Earth is flat.  "
        result = ingest(claim)
        assert result["success"] is True
        assert result["raw_text"] == claim.strip()

    def test_multiline_plain_text(self):
        claim = "Line one.\nLine two.\nLine three."
        result = ingest(claim)
        assert result["source_type"] == "text"
        assert result["success"] is True
        assert "Line one" in result["raw_text"]

    def test_empty_string_fails_gracefully(self):
        result = ingest("")
        assert result["success"] is False
        assert result["raw_text"] is None
        assert result["error"] is not None

    def test_whitespace_only_fails_gracefully(self):
        result = ingest("   \n\t  ")
        assert result["success"] is False
        assert result["raw_text"] is None


class TestOutOfScopeUrls:
    def test_instagram_returns_clear_error(self):
        url = "https://www.instagram.com/reel/ABC123/"
        result = ingest(url)
        assert result["success"] is False
        assert "Instagram" in result["error"] or "out of scope" in result["error"]

    def test_tiktok_returns_clear_error(self):
        url = "https://www.tiktok.com/@user/video/1234567890"
        result = ingest(url)
        assert result["success"] is False
        assert "TikTok" in result["error"] or "out of scope" in result["error"]


# ===========================================================================
# Network-dependent tests  (require internet access)
# ===========================================================================

@pytest.mark.slow
class TestYouTube:
    # "Me at the zoo" — the very first YouTube video (2005), public, has
    # auto-generated English captions, is unlikely to ever be taken down.
    VALID_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"

    # A well-formed but non-existent video ID (11 chars, all valid chars)
    INVALID_URL = "https://www.youtube.com/watch?v=XXXXXXXXXXX"

    # youtu.be short-link format — same video as VALID_URL
    SHORT_LINK_URL = "https://youtu.be/jNQXAC9IVRw"

    def test_valid_youtube_url_returns_transcript(self):
        result = ingest(self.VALID_URL)
        assert result["source_type"] == "youtube"
        assert result["success"] is True, f"Expected success but got error: {result['error']}"
        assert isinstance(result["raw_text"], str)
        assert len(result["raw_text"]) > 10, "Transcript text was unexpectedly short"
        assert result["error"] is None

    def test_short_link_format_works(self):
        result = ingest(self.SHORT_LINK_URL)
        assert result["source_type"] == "youtube"
        assert result["success"] is True, f"Short-link failed: {result['error']}"
        assert result["raw_text"]

    def test_invalid_video_id_fails_gracefully(self):
        result = ingest(self.INVALID_URL)
        assert result["source_type"] == "youtube"
        assert result["success"] is False
        assert result["raw_text"] is None
        assert result["error"] is not None
        # Error message should be informative, not a raw traceback
        assert len(result["error"]) > 5


@pytest.mark.slow
class TestArticle:
    # Wikipedia is extremely stable and always machine-readable
    WIKI_URL = "https://en.wikipedia.org/wiki/Protein"

    # A domain that does not resolve — should fail gracefully, not raise
    BAD_URL = "https://this-domain-does-not-exist-at-all-xyz123.com/article"

    def test_wikipedia_article_extracts_text(self):
        result = ingest(self.WIKI_URL)
        assert result["source_type"] == "article"
        assert result["success"] is True, f"Expected success but got error: {result['error']}"
        assert isinstance(result["raw_text"], str)
        assert len(result["raw_text"]) > 100, "Article text was unexpectedly short"
        assert result["error"] is None
        # Sanity-check that we got actual article content
        assert "protein" in result["raw_text"].lower()

    def test_unreachable_url_fails_gracefully(self):
        result = ingest(self.BAD_URL)
        assert result["source_type"] == "article"
        assert result["success"] is False
        assert result["raw_text"] is None
        assert result["error"] is not None
