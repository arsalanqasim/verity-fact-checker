"""
Tests for src/pipeline/ingestion.py

Per project convention (PROJECT_CONTEXT.md):
  Every pipeline module needs a unit test with a fixed input/output before
  it is considered done.

Planned test cases (to be implemented in Phase 1):
  - test_plain_text_passthrough: raw string → same string returned, type=TEXT
  - test_youtube_url_detected: YouTube URL → type=YOUTUBE, transcript fetched
  - test_article_url_detected: article URL → type=ARTICLE, body text extracted
  - test_unsupported_url_raises: Instagram/TikTok URL → NotImplementedError
"""

# import pytest
# from src.pipeline.ingestion import ingest


def test_placeholder():
    """Placeholder — replace with real tests when ingestion.py is implemented."""
    assert True
