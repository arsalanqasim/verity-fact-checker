"""
Stage 3 — Verification

Responsibility:
  Given a typed claim from the Claim Extraction stage, query the Brave Search
  MCP server for evidence and return results annotated with source authority
  scores, ready for Verdict Synthesis.

Key design decisions:
  - Primary verification mechanism: Brave Search MCP server (SSE transport).
    Client uses the official ``mcp`` Python SDK (``mcp.client.sse.sse_client``
    + ``mcp.ClientSession``).  This is the actual fact-finding layer; it is
    NOT Slack's RTS (in-workspace search).
  - Comparative claims get ONE SEARCH PER COMPARED ITEM — not a single blended
    query.  This prevents the model from averaging across subjects and ensures
    each item has independently sourced evidence before comparison.
  - Source-quality ranking is an EXPLICIT, INSPECTABLE function (``score_authority``).
    This is a named, deliberate design decision — not buried middleware.
    Tier 1 (.gov/.edu/primary sources) → 0.75–1.00
    Tier 2 (established news wires/quality outlets) → 0.45–0.74
    Tier 3 (general web/blogs/aggregators) → 0.10–0.44
    Results from all tiers are returned; Verdict Synthesis uses the scores to
    weight evidence — lower-tier results are included but do not dominate.
  - Returns a flat evidence list sorted by authority_score descending so the
    Verdict stage always sees the most authoritative sources first.

Public API:
  ``verify_claim(claim, claim_type, compared_items) -> dict``
  ``score_authority(url: str) -> float``   (exported for tests and pitching)

Return schema:
  {
    "evidence": [
      {
        "source_url":      str,
        "snippet":         str,
        "title":           str,
        "authority_score": float,   # 0.0 – 1.0
        "authority_tier":  int,     # 1 | 2 | 3
        "query":           str,     # which search query produced this result
      },
      ...
    ],
    "success": bool,
    "error":   str | None,
  }

Environment:
  BRAVE_SEARCH_MCP_URL — SSE endpoint of the Brave Search MCP server,
                         e.g. http://localhost:3001/sse
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Optional
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Authority scoring — the explicit design decision
# ---------------------------------------------------------------------------

# Tier 1: Primary sources — highest epistemic authority for fact-checking
_TIER1_TLDS = {"gov", "edu", "mil"}
_TIER1_EXACT_DOMAINS = {
    # Health / science databases
    "pubmed.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
    "nih.gov",
    "cdc.gov",
    "who.int",
    "fda.gov",
    "usda.gov",
    "nhs.uk",
    "mayoclinic.org",
    # Peer-reviewed journals
    "nature.com",
    "science.org",
    "thelancet.com",
    "nejm.org",
    "bmj.com",
    "cell.com",
    "jamanetwork.com",
    "plos.org",
    "frontiersin.org",
    "mdpi.com",
    "springer.com",
    "wiley.com",
    "tandfonline.com",
    "oxfordjournals.org",
    # Nutrition / food science primary sources
    "nutritiondata.self.com",
    "fdc.nal.usda.gov",
    "examine.com",
}

# Tier 2: Established news wires and known-quality outlets
_TIER2_DOMAINS = {
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "theguardian.com",
    "nytimes.com",
    "washingtonpost.com",
    "scientificamerican.com",
    "theatlantic.com",
    "economist.com",
    "politifact.com",
    "snopes.com",
    "factcheck.org",
    "fullfact.org",
    "health.harvard.edu",
    "hsph.harvard.edu",
    "hopkinsmedicine.org",
    "clevelandclinic.org",
    "medicalnewstoday.com",
    "healthline.com",
    "webmd.com",
}

# Tier 3: Everything else (generic web, blogs, aggregators, social) — score
# calculated from recency / position signals alone (floor 0.10).


def score_authority(url: str) -> tuple[float, int]:
    """
    Score a URL by source authority.  Returns ``(score, tier)`` where:
      - score ∈ [0.0, 1.0]
      - tier  ∈ {1, 2, 3}

    This function is the named, deliberate design decision referenced in the
    pitch: we do NOT treat all search results equally.  Tier-1 sources anchor
    the verdict; lower-tier sources add context but do not dominate.

    Scoring rationale:
      Tier 1 (0.75 – 1.00) — .gov / .edu / .mil TLDs, named peer-reviewed
        journals, and primary databases (PubMed, USDA FoodData, WHO, etc.).
        These are first-party or editorially independent primary sources.
      Tier 2 (0.45 – 0.74) — Established news wires (Reuters, AP), reputable
        broadsheets, and specialist fact-checkers with editorial standards.
      Tier 3 (0.10 – 0.44) — All other web content.  Included in evidence
        but weighted down so the verdict is not laundered through blog posts.
    """
    if not url:
        return 0.1, 3

    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        hostname = hostname.lower().lstrip("www.")
    except Exception:
        return 0.1, 3

    # --- Tier 1 ---
    # Check by TLD (.gov, .edu, .mil) — covers all government and
    # educational institution domains regardless of specific hostname.
    tld = hostname.rsplit(".", 1)[-1] if "." in hostname else ""
    if tld in _TIER1_TLDS:
        return 0.95, 1

    # Check exact known Tier-1 domains (journals, primary databases)
    for t1 in _TIER1_EXACT_DOMAINS:
        if hostname == t1 or hostname.endswith("." + t1):
            return 0.88, 1

    # --- Tier 2 ---
    for t2 in _TIER2_DOMAINS:
        if hostname == t2 or hostname.endswith("." + t2):
            return 0.60, 2

    # --- Tier 3 ---
    return 0.20, 3


# ---------------------------------------------------------------------------
# MCP client helpers  (async)
# ---------------------------------------------------------------------------

_TOOL_NAME = "brave_web_search"
_RESULTS_PER_QUERY = 5   # Brave MCP default is 10; 5 is enough per query


async def _call_brave_mcp(
    mcp_url: str,
    query: str,
    count: int = _RESULTS_PER_QUERY,
) -> list[dict]:
    """
    Connect to the Brave Search MCP server via SSE transport, call the
    ``brave_web_search`` tool, and parse the results into a list of dicts:
      [{"title": str, "url": str, "snippet": str}, ...]

    Uses ``mcp.client.sse.sse_client`` + ``mcp.ClientSession`` from the
    official MCP Python SDK (mcp>=1.28).
    """
    from mcp.client.sse import sse_client
    from mcp import ClientSession

    async with sse_client(url=mcp_url, timeout=15) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                _TOOL_NAME,
                {"query": query, "count": count},
            )

    if result.isError:
        raise RuntimeError(f"MCP tool returned an error for query '{query}'")

    return _parse_tool_result(result.content)


def _parse_tool_result(content_items) -> list[dict]:
    """
    Parse the ``CallToolResult.content`` list from the Brave Search MCP server.

    The Brave Search MCP server returns results as a JSON string embedded in
    a ``TextContent`` object.  The JSON top-level structure is:
      {"web": {"results": [{"title": ..., "url": ..., "description": ...}, ...]}}

    We also handle a plain-list format used by some server versions.
    """
    results: list[dict] = []

    for item in content_items:
        # TextContent has a `.text` attribute
        text = getattr(item, "text", None)
        if not text:
            continue

        # --- Try JSON parse first ---
        try:
            data = json.loads(text)

            # Format A: {"web": {"results": [...]}}
            web_results = (
                data.get("web", {}).get("results", [])
                if isinstance(data, dict)
                else []
            )

            # Format B: top-level list of result objects
            if not web_results and isinstance(data, list):
                web_results = data

            for r in web_results:
                if isinstance(r, dict) and r.get("url"):
                    results.append({
                        "title":   r.get("title", ""),
                        "url":     r.get("url", ""),
                        "snippet": r.get("description", r.get("snippet", "")),
                    })
            if results:
                continue
        except (json.JSONDecodeError, AttributeError):
            pass

        # --- Fallback: parse free-text format ---
        # Some server versions return:
        #   Title: ...
        #   URL: https://...
        #   Description: ...
        #   ---
        blocks = re.split(r"\n[-]{3,}\n", text)
        for block in blocks:
            url_m = re.search(r"(?:URL|Link):\s*(https?://\S+)", block, re.IGNORECASE)
            title_m = re.search(r"Title:\s*(.+)", block, re.IGNORECASE)
            desc_m = re.search(r"(?:Description|Snippet):\s*(.+)", block, re.IGNORECASE | re.DOTALL)
            if url_m:
                results.append({
                    "title":   title_m.group(1).strip() if title_m else "",
                    "url":     url_m.group(1).strip(),
                    "snippet": desc_m.group(1).strip()[:300] if desc_m else "",
                })

    return results


# ---------------------------------------------------------------------------
# Evidence gathering — the per-item query strategy for comparative claims
# ---------------------------------------------------------------------------

async def _gather_evidence_for_query(
    mcp_url: str,
    query: str,
    label: str,
) -> list[dict]:
    """
    Run one search query and annotate each result with authority score, tier,
    and the query that produced it.
    """
    raw = await _call_brave_mcp(mcp_url, query)
    evidence = []
    for item in raw:
        score, tier = score_authority(item.get("url", ""))
        evidence.append({
            "source_url":      item.get("url", ""),
            "title":           item.get("title", ""),
            "snippet":         item.get("snippet", ""),
            "authority_score": score,
            "authority_tier":  tier,
            "query":           label,
        })
    return evidence


def _build_queries(
    claim: str,
    claim_type: str,
    compared_items: Optional[list[str]],
) -> list[tuple[str, str]]:
    """
    Return a list of (query_string, label) pairs to run.

    Comparative claims get one query per compared item so evidence is gathered
    independently for each subject — critical for correct verdict synthesis on
    ranking/comparison claims.
    """
    if claim_type == "comparative" and compared_items:
        queries = []
        for item in compared_items:
            # Extract the core property being compared from the claim.
            # E.g. "Lentils have more protein per 100g than chicken and eggs"
            # → query: "lentils protein content per 100g nutritional data"
            queries.append((f"{item} {_extract_property(claim)}", item))
        # Also add one broad query for the overall claim as context
        queries.append((claim, "overall"))
        return queries

    # For single_fact and causal: one direct query + one broader context query
    return [
        (claim, "direct"),
        (_broaden_query(claim), "context"),
    ]


def _extract_property(claim: str) -> str:
    """
    Heuristically extract the property being compared from a comparative claim.
    E.g. "X has more protein than Y" → "protein content nutritional data"
    Falls back to a generic "facts data" if no property is detectable.
    """
    # Look for common nutrition/science property words
    patterns = [
        r"\b(protein|fat|carb\w*|calori\w*|vitamin\w*|mineral\w*|fibre?|sugar|sodium)\b",
        r"\b(efficacy|risk|rate|level|amount|concentration|dosage|percentage)\b",
    ]
    for pat in patterns:
        m = re.search(pat, claim, re.IGNORECASE)
        if m:
            return f"{m.group(1)} content nutritional data"
    return "facts data scientific evidence"


def _broaden_query(claim: str) -> str:
    """
    Create a broader context query by appending evidence-seeking terms.
    """
    return f"{claim} scientific evidence research"


# ---------------------------------------------------------------------------
# Async orchestrator
# ---------------------------------------------------------------------------

async def _verify_async(
    mcp_url: str,
    claim: str,
    claim_type: str,
    compared_items: Optional[list[str]],
) -> dict:
    """Async core — gathers evidence for all queries and returns sorted results."""
    queries = _build_queries(claim, claim_type, compared_items)

    all_evidence: list[dict] = []
    errors: list[str] = []

    for query_str, label in queries:
        try:
            ev = await _gather_evidence_for_query(mcp_url, query_str, label)
            all_evidence.extend(ev)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Query '{label}' failed: {exc}")

    if not all_evidence and errors:
        return {
            "evidence": [],
            "success": False,
            "error": "; ".join(errors),
        }

    # Deduplicate by URL, keeping the highest-scored copy
    seen: dict[str, dict] = {}
    for item in all_evidence:
        url = item["source_url"]
        if url not in seen or item["authority_score"] > seen[url]["authority_score"]:
            seen[url] = item

    # Sort: Tier 1 first, then by score descending
    sorted_evidence = sorted(
        seen.values(),
        key=lambda x: (-x["authority_tier"] * -1, -x["authority_score"]),
    )

    return {
        "evidence": sorted_evidence,
        "success": True,
        "error": "; ".join(errors) if errors else None,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def search_workspace_history(query: str) -> list[dict]:
    """
    Search the Slack workspace for discussions matching the query.
    Requires SLACK_USER_TOKEN (xoxp-) in env with 'search:read' scope.
    """
    import logging
    logger = logging.getLogger(__name__)

    user_token = os.environ.get("SLACK_USER_TOKEN", "").strip()
    if not user_token:
        logger.info("SLACK_USER_TOKEN not set; skipping workspace history search.")
        return []

    try:
        from slack_sdk import WebClient
        import datetime

        client = WebClient(token=user_token)
        response = client.search_messages(query=query, count=5)
        if not response.get("ok"):
            logger.warning(f"Slack search_messages failed: {response.get('error')}")
            return []

        matches = response.get("messages", {}).get("matches", [])
        discussions = []
        for m in matches:
            channel_data = m.get("channel", {})
            channel_name = channel_data.get("name", "unknown-channel")
            if channel_name and not channel_name.startswith("#"):
                channel_name = f"#{channel_name}"

            ts = m.get("ts")
            date_str = "unknown date"
            if ts:
                try:
                    date_str = datetime.datetime.fromtimestamp(float(ts)).strftime('%Y-%m-%d')
                except Exception:
                    pass

            discussions.append({
                "channel_name": channel_name,
                "date": date_str,
                "permalink": m.get("permalink", ""),
                "text": m.get("text", "")
            })
        return discussions
    except Exception as exc:
        logger.warning(f"Error during workspace search: {exc}")
        return []


def verify_claim(
    claim: str,
    claim_type: str,
    compared_items: Optional[list[str]] = None,
) -> dict:
    """
    Gather evidence for ``claim`` from the Brave Search MCP server and return
    source-quality-ranked results, along with optional prior workspace discussions.

    Parameters
    ----------
    claim:
        The checkable claim sentence from extract_claim().
    claim_type:
        ``"single_fact"``, ``"comparative"``, ``"causal"``, or ``"other"``.
    compared_items:
        For comparative claims, the list of entities being compared.  Each
        gets its own dedicated search query.

    Returns
    -------
    dict with keys:
      - ``evidence``  : list of evidence dicts, sorted by authority_score desc
      - ``workspace_discussions`` : list of prior conversations found via Slack RTS
      - ``success``   : True if at least some evidence was gathered
      - ``error``     : None on full success, partial-error message otherwise
    """
    if not claim or not claim.strip():
        return {
            "evidence": [],
            "workspace_discussions": [],
            "success": False,
            "error": "Claim was empty."
        }

    mcp_url = os.environ.get("BRAVE_SEARCH_MCP_URL", "").strip()
    if not mcp_url:
        return {
            "evidence": [],
            "workspace_discussions": search_workspace_history(claim.strip()),
            "success": False,
            "error": (
                "BRAVE_SEARCH_MCP_URL is not set. Start the Brave Search MCP "
                "server and set this env var to its SSE endpoint "
                "(e.g. http://localhost:3001/sse)."
            ),
        }

    try:
        res = asyncio.run(
            _verify_async(mcp_url, claim.strip(), claim_type, compared_items)
        )
        res["workspace_discussions"] = search_workspace_history(claim.strip())
        return res
    except Exception as exc:  # noqa: BLE001
        return {
            "evidence": [],
            "workspace_discussions": search_workspace_history(claim.strip()),
            "success": False,
            "error": f"Verification failed: {exc}",
        }
