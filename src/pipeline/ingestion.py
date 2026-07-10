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
  - YouTube transcripts are fetched with `youtube-transcript-api`.
  - Article/web pages are extracted with `trafilatura`.
  - Plain text is passed through as-is (zero ingestion risk — this is the
    primary demo path).
  - Instagram Reels and TikTok are explicitly out of scope for MVP; any attempt
    to pass those URLs will raise a NotImplementedError so callers know early.
"""
