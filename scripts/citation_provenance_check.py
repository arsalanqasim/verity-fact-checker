"""
Citation Provenance Diagnostic
===============================
Runs the Great Wall claim through run_agent() with full, untruncated evidence
logging, then diffs the retrieved URLs against the URLs in the synthesized
verdict to detect hallucinated citations.

Run:
    venv\\Scripts\\python scripts\\citation_provenance_check.py
"""

import logging
import sys
import os

# Enable DEBUG on the agent module so we see every tool response untruncated.
# We override search_web_evidence to intercept and record the full text.
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)

# ── Intercept search_web_evidence before run_agent imports it ─────────────────
import src.pipeline.agent as _agent_mod
from src.pipeline.verification import verify_claim

_RETRIEVED_EVIDENCE: list[dict] = []  # accumulates raw evidence dicts per call

_original_search = _agent_mod.search_web_evidence

def _intercepted_search(query: str) -> str:
    """
    Wraps search_web_evidence to:
    1. Dump the full, untruncated evidence list (every URL, title, tier).
    2. Record all retrieved URLs for provenance checking.
    """
    print(f"\n{'='*72}")
    print(f"TOOL CALL: search_web_evidence(query={query!r})")
    print(f"{'='*72}")

    res = verify_claim(query, claim_type="single_fact")

    if not res.get("success"):
        print(f"  [SEARCH FAILED] error: {res.get('error')}")
        return f"Search error: {res.get('error', 'unknown error')}"

    evidence = res.get("evidence", [])
    if not evidence:
        print(f"  [NO RESULTS] No evidence returned.")
        return f"No search results found for query: '{query}'."

    print(f"  [EVIDENCE — {len(evidence)} items returned]")
    for idx, item in enumerate(evidence, start=1):
        url   = item.get("source_url", "")
        title = item.get("title", "")
        tier  = item.get("authority_tier", "?")
        score = item.get("authority_score", 0.0)
        snippet = item.get("snippet", "")[:120]
        print(f"\n  [{idx}] Tier {tier} | Score {score:.2f}")
        print(f"       URL   : {url}")
        print(f"       Title : {title}")
        print(f"       Snip  : {snippet}")
        _RETRIEVED_EVIDENCE.append(item)

    # Return the same formatted string the real function would
    formatted = []
    for idx, item in enumerate(evidence, start=1):
        formatted.append(
            f"Evidence [{idx}]:\n"
            f"  Title: {item.get('title')}\n"
            f"  URL: {item.get('source_url')}\n"
            f"  Tier: {item.get('authority_tier')}\n"
            f"  Score: {item.get('authority_score'):.2f}\n"
            f"  Snippet: {item.get('snippet')}\n"
        )
    return "\n".join(formatted)


# Patch the module-level function before run_agent() references it
_agent_mod.search_web_evidence = _intercepted_search

# ── Run the claim ──────────────────────────────────────────────────────────────
CLAIM = "The Great Wall of China is visible from space with the naked eye"

print(f"\n{'#'*72}")
print(f"CLAIM: {CLAIM}")
print(f"{'#'*72}\n")

from src.pipeline.agent import run_agent
result = run_agent(CLAIM)

# ── Print the synthesized verdict ─────────────────────────────────────────────
print(f"\n{'='*72}")
print("SYNTHESIZED VERDICT")
print(f"{'='*72}")
print(f"  Verdict    : {result.get('verdict')}")
print(f"  Confidence : {result.get('confidence')}")
print(f"  search_ok  : {result.get('search_succeeded')}")
print(f"  Summary    : {result.get('summary')}")
print(f"\n  Sources in verdict ({len(result.get('sources', []))}):")
verdict_sources = result.get("sources", [])
for s in verdict_sources:
    print(f"    • [{s.get('tier')}] {s.get('url')}")
    print(f"          title: {s.get('title')}")

# ── Provenance diff ───────────────────────────────────────────────────────────
print(f"\n{'='*72}")
print("PROVENANCE DIFF")
print(f"{'='*72}")

retrieved_urls = {item.get("source_url", "").strip() for item in _RETRIEVED_EVIDENCE}
verdict_urls   = {s.get("url", "").strip() for s in verdict_sources}

hallucinated = verdict_urls - retrieved_urls
confirmed    = verdict_urls & retrieved_urls
unreferenced = retrieved_urls - verdict_urls

print(f"\n  Retrieved URLs  : {len(retrieved_urls)}")
print(f"  Verdict URLs    : {len(verdict_urls)}")
print(f"  Confirmed (in both)  : {len(confirmed)}")
print(f"  HALLUCINATED (verdict only, NOT in evidence): {len(hallucinated)}")
print(f"  Unreferenced (retrieved but not cited) : {len(unreferenced)}")

if hallucinated:
    print(f"\n  *** HALLUCINATED CITATIONS ***")
    for url in sorted(hallucinated):
        print(f"    !! {url}")
else:
    print(f"\n  ✓ All verdict URLs appeared in the retrieved evidence.")

if confirmed:
    print(f"\n  Confirmed citations:")
    for url in sorted(confirmed):
        print(f"    ✓ {url}")

if unreferenced:
    print(f"\n  Unreferenced (retrieved but not used in verdict):")
    for url in sorted(unreferenced):
        print(f"    - {url}")

print(f"\n{'#'*72}")
print("DIAGNOSTIC COMPLETE")
print(f"{'#'*72}\n")
