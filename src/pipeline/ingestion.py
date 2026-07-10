"""
Stage 1 — Ingestion

Responsibility:
  Detect the type of input supplied by the user (plain text, YouTube URL,
  article/news URL, or any future media link) and route it to the appropriate
  extractor.  Returns a normalised plain-text string that downstream pipeline
  stages can consume without needing to know the original input type.

Key design decisions:
  - Input types are detected via URL pattern matching; no external call is made
    at the routing layer itself.
  - YouTube transcripts are fetched with ``youtube-transcript-api`` (v1.x API:
    ``YouTubeTranscriptApi().fetch(video_id)`` → ``FetchedTranscript``).
  - Article/web pages are extracted with ``trafilatura``.
  - Plain text is passed through as-is (zero ingestion risk — this is the
    primary demo path and the first thing to prove end-to-end).
  - All failure paths return ``{"success": False, "error": "<reason>"}``
    rather than raising, so callers can handle errors gracefully without
    try/except boilerplate.
  - Instagram Reels and TikTok are explicitly out of scope for MVP; any attempt
    to pass those URLs returns a clear ``NotImplemented`` error string so
    callers know early and can surface a useful message to the user.

Public API:
  ``ingest(input_str: str) -> dict``

Return schema:
  {
    "source_type": "youtube" | "article" | "text",
    "raw_text":    str | None,
    "success":     bool,
    "error":       str | None,
  }
"""

from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------------
# URL pattern helpers
# ---------------------------------------------------------------------------

# Matches the 11-character video ID from all common YouTube URL shapes:
#   https://www.youtube.com/watch?v=VIDEO_ID
#   https://youtu.be/VIDEO_ID
#   https://www.youtube.com/embed/VIDEO_ID
#   https://www.youtube.com/shorts/VIDEO_ID
_YT_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})"
)

# Matches any http/https URL (used to distinguish URLs from plain text)
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

# Out-of-scope domains — returned as a clear error rather than silently failing
_OOS_RE = re.compile(r"instagram\.com|tiktok\.com", re.IGNORECASE)


def _extract_youtube_id(url: str) -> Optional[str]:
    """Return the 11-char video ID from a YouTube URL, or None if not matched."""
    m = _YT_ID_RE.search(url)
    return m.group(1) if m else None


def _is_url(text: str) -> bool:
    return bool(_URL_RE.match(text.strip()))


# ---------------------------------------------------------------------------
# Per-type extractors
# ---------------------------------------------------------------------------

def _ingest_youtube(url: str) -> dict:
    """Fetch the transcript for a YouTube video URL."""
    video_id = _extract_youtube_id(url)
    if not video_id:
        return {
            "source_type": "youtube",
            "raw_text": None,
            "success": False,
            "error": f"Could not extract a YouTube video ID from URL: {url!r}",
        }

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import (
            NoTranscriptFound,
            TranscriptsDisabled,
            VideoUnavailable,
        )

        ytt_api = YouTubeTranscriptApi()

        try:
            # v1.x: fetch() → FetchedTranscript (iterable of FetchedTranscriptSnippet)
            fetched = ytt_api.fetch(video_id)
            raw_text = " ".join(snippet.text for snippet in fetched).strip()
        except NoTranscriptFound:
            return {
                "source_type": "youtube",
                "raw_text": None,
                "success": False,
                "error": (
                    f"No transcript found for video '{video_id}'. "
                    "The video may have disabled captions or none are available "
                    "in a supported language."
                ),
            }
        except TranscriptsDisabled:
            return {
                "source_type": "youtube",
                "raw_text": None,
                "success": False,
                "error": (
                    f"Transcripts are disabled for video '{video_id}'."
                ),
            }
        except VideoUnavailable:
            return {
                "source_type": "youtube",
                "raw_text": None,
                "success": False,
                "error": f"Video '{video_id}' is unavailable (private, deleted, or region-locked).",
            }

        if not raw_text:
            return {
                "source_type": "youtube",
                "raw_text": None,
                "success": False,
                "error": f"Transcript for video '{video_id}' was empty.",
            }

        return {
            "source_type": "youtube",
            "raw_text": raw_text,
            "success": True,
            "error": None,
        }

    except Exception as exc:  # noqa: BLE001 — catch-all so the pipeline never crashes
        return {
            "source_type": "youtube",
            "raw_text": None,
            "success": False,
            "error": f"Unexpected error fetching YouTube transcript: {exc}",
        }


def _ingest_article(url: str) -> dict:
    """Download and extract main body text from an article/news URL."""
    try:
        import trafilatura

        downloaded = trafilatura.fetch_url(url)
        if downloaded is None:
            return {
                "source_type": "article",
                "raw_text": None,
                "success": False,
                "error": f"Failed to download content from URL: {url!r}",
            }

        raw_text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )

        if not raw_text or not raw_text.strip():
            return {
                "source_type": "article",
                "raw_text": None,
                "success": False,
                "error": (
                    f"Could not extract readable text from URL: {url!r}. "
                    "The page may be JavaScript-rendered, paywalled, or empty."
                ),
            }

        return {
            "source_type": "article",
            "raw_text": raw_text.strip(),
            "success": True,
            "error": None,
        }

    except Exception as exc:  # noqa: BLE001
        return {
            "source_type": "article",
            "raw_text": None,
            "success": False,
            "error": f"Unexpected error extracting article: {exc}",
        }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def ingest(input_str: str) -> dict:
    """
    Detect the input type and extract raw text suitable for claim extraction.

    Parameters
    ----------
    input_str:
        A plain-text claim, a YouTube video URL, or an article/news URL.

    Returns
    -------
    dict with keys:
      - ``source_type``: ``"youtube"`` | ``"article"`` | ``"text"``
      - ``raw_text``:    extracted text, or ``None`` on failure
      - ``success``:     ``True`` if extraction succeeded
      - ``error``:       human-readable error string, or ``None`` on success
    """
    text = input_str.strip() if input_str else ""

    if not text:
        return {
            "source_type": "text",
            "raw_text": None,
            "success": False,
            "error": "Input was empty or whitespace-only.",
        }

    if not _is_url(text):
        # Plain text — passthrough, no network call needed
        return {
            "source_type": "text",
            "raw_text": text,
            "success": True,
            "error": None,
        }

    # --- URL branch ---

    # Out-of-scope check first so the error message is clear
    if _OOS_RE.search(text):
        return {
            "source_type": "article",
            "raw_text": None,
            "success": False,
            "error": (
                "Instagram and TikTok URLs are out of scope for the MVP. "
                "Please paste the claim as plain text instead."
            ),
        }

    # YouTube detection: either the domain contains youtube/youtu.be
    # OR the regex finds a video ID (handles edge cases like tracking params)
    if "youtube.com" in text or "youtu.be" in text:
        return _ingest_youtube(text)

    # Everything else is treated as a generic article/web URL
    return _ingest_article(text)
