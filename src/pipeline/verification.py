"""
Stage 3 — Verification

Responsibility:
  Given one or more typed claims from the Claim Extraction stage, query
  external sources for evidence and return ranked search results annotated
  with source quality scores.

Key design decisions:
  - Primary verification mechanism: Brave Search MCP server (web-search MCP).
    This is the actual fact-finding layer; it is NOT a Slack in-workspace
    search.  MCP client calls are made here, not in the Slack app.
  - Secondary / bonus: Slack RTS (Real-Time Search) API — used ONLY to check
    whether this claim has been previously discussed inside the current Slack
    workspace ("workspace memory").  RTS does not and cannot search the
    internet.
  - Source-quality ranking is a deliberate, named design decision:
      Tier 1 — .gov / .edu / peer-reviewed journals / primary databases
      Tier 2 — established news wire / known-quality outlets
      Tier 3 — generic web / blogs / social content
    Results from lower tiers are included but weighted down in verdict
    synthesis so the final verdict is not laundered through low-quality hits.
  - Returns a VerificationResult containing weighted evidence items so the
    Verdict stage can reason over source quality, not just content.
"""
