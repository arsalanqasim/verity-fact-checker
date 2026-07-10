"""
Stage 4 — Verdict Synthesis

Responsibility:
  Given the weighted evidence bundle from the Verification stage, make a
  final LLM call (Claude) that produces a structured verdict ready for
  Slack delivery.

Key design decisions:
  - Verdict labels are exactly four: True | False | Misleading | Unverifiable.
    No other labels are permitted so downstream Block Kit formatting stays
    deterministic.
  - Output is always structured JSON (no free-text parsing):
      {
        "verdict": "True" | "False" | "Misleading" | "Unverifiable",
        "confidence": 0.0–1.0,
        "summary": "one-sentence human-readable explanation",
        "sources": [{"title": ..., "url": ..., "tier": 1|2|3}, ...]
      }
  - The LLM is explicitly instructed to weight Tier-1 sources more heavily
    and to label a claim "Unverifiable" when no Tier-1 or Tier-2 evidence is
    available — preventing false confidence from blog aggregation.
  - Confidence score is surfaced to users; callers should treat anything below
    a project-defined threshold (TBD) as automatically "Unverifiable" in UX.
"""
