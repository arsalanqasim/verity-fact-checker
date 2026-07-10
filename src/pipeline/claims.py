"""
Stage 2 — Claim Extraction

Responsibility:
  Given the raw text produced by the Ingestion stage, identify the specific,
  checkable claim(s) contained in that text via a structured LLM call to the
  Claude API (Anthropic).

Key design decisions:
  - Uses Claude with structured JSON output (no free-text parsing).
  - Correctly classifies claim *type*:
      • Single factual claim  — one discrete, verifiable assertion.
      • Comparative/superlative claim — e.g. "X has more protein than Y and Z"
        must be evaluated as a ranking claim, not decomposed into independent
        single-fact checks.
      • Causal claim — assertion that A causes B.
  - Returns a list of typed ClaimResult objects; callers iterate them
    independently so each can be verified separately.
  - Prompt engineering for claim extraction is the primary quality lever here —
    this module should be tweaked and retested whenever claim type accuracy is
    poor on real examples.
"""
