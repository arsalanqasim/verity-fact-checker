"""
Stage 5 — Enterprise Reporting & Directories (Slack Canvas & Lists)

Responsibility:
  Interacts with Slack's Canvases API to construct and publish detailed fact-check
  reports, and with Slack's Lists API to maintain a persistent Claim Directory.
"""

from __future__ import annotations

import logging
import os
from dotenv import load_dotenv
from slack_sdk.errors import SlackApiError

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Slack Canvas Reporting
# ---------------------------------------------------------------------------

def create_fact_check_canvas(client, claim: str, agent_res: dict) -> str | None:
    """
    Create a detailed Slack Canvas document with a formatted fact-checking report.
    
    Parameters:
        client: The WebClient instance from Bolt.
        claim: The text claim checked.
        agent_res: The dict result from run_agent.
        
    Returns:
        The URL of the created canvas, or None if creation failed/unsupported.
    """
    try:
        verdict = agent_res.get("verdict", "Unverifiable")
        confidence = agent_res.get("confidence", 0.0)
        summary = agent_res.get("summary", "")
        sources = agent_res.get("sources", [])
        
        # Build document content in standard Markdown format (required by Canvases API)
        md_content = (
            f"# ⚖️ Verity Fact-Check Report\n\n"
            f"### Claim Evaluated\n"
            f"> {claim}\n\n"
            f"### Synthesis Verdict\n"
            f"* **Verdict:** `{verdict}`\n"
            f"* **Confidence Score:** `{confidence:.2f}`\n\n"
            f"---\n\n"
            f"## 📝 Executive Summary\n"
            f"{summary}\n\n"
            f"## 🛡️ Evidence & Citations\n"
        )
        
        if sources:
            for idx, src in enumerate(sources, start=1):
                md_content += f"{idx}. **[{src.get('title')}]({src.get('url')})** (Tier {src.get('tier')})\n"
        else:
            md_content += "_No external sources cited for this claim._\n"
            
        md_content += "\n---\n_Report compiled automatically by Verity Fact-Checking Agent._"

        logger.info(f"Creating Slack Canvas report for: '{claim[:30]}...'")
        
        # Call canvases.create
        res = client.canvases_create(
            title=f"Verity Report: {claim[:30]}",
            document_content={
                "type": "markdown",
                "markdown": md_content
            }
        )
        
        if res.get("ok"):
            canvas_id = res["canvas_id"]
            canvas_url = f"https://slack.com/canvas/{canvas_id}"
            logger.info(f"Created Canvas {canvas_id}")
            return canvas_url
            
    except SlackApiError as exc:
        error_code = exc.response.get("error") if exc.response else None
        if error_code in ("missing_scope", "feature_not_enabled", "method_not_supported"):
            missing = exc.response.get("needed") or "canvases:write"
            logger.warning(f"Skipped because of permissions: missing {missing}")
            return None
        logger.error(f"Slack API error during Canvas creation: {exc}", exc_info=True)
        return None
    except Exception as exc:
        logger.error(f"Unexpected error during Canvas creation: {exc}", exc_info=True)
        return None

# ---------------------------------------------------------------------------
# Slack Lists Logging
# ---------------------------------------------------------------------------

def add_claim_to_list(client, claim: str, agent_res: dict) -> bool:
    """
    Log the factual claim and its verdict into a workspace Slack List for moderation.
    
    Parameters:
        client: The WebClient instance from Bolt.
        claim: The claim statement.
        agent_res: The dict result from run_agent.
        
    Returns:
        True if successfully logged, False otherwise.
    """
    list_id = os.environ.get("SLACK_LIST_ID")
    if not list_id or not list_id.strip():
        logger.info("SLACK_LIST_ID not configured — skipping Slack Lists logging.")
        return False
        
    col_claim = os.environ.get("SLACK_LIST_COL_CLAIM")
    col_verdict = os.environ.get("SLACK_LIST_COL_VERDICT")
    col_confidence = os.environ.get("SLACK_LIST_COL_CONFIDENCE")
    col_summary = os.environ.get("SLACK_LIST_COL_SUMMARY")
    
    if not any([col_claim, col_verdict, col_confidence, col_summary]):
        logger.warning("Slack List column mappings (SLACK_LIST_COL_*) not configured.")
        return False
        
    try:
        verdict = agent_res.get("verdict", "Unverifiable")
        confidence = agent_res.get("confidence", 0.0)
        summary = agent_res.get("summary", "")
        
        # Build initial_fields dictionary mapping user's list schemas
        fields = []
        if col_claim:
            fields.append({"column_id": col_claim, "text": claim})
        if col_verdict:
            fields.append({"column_id": col_verdict, "text": verdict})
        if col_confidence:
            fields.append({"column_id": col_confidence, "text": f"{confidence:.2f}"})
        if col_summary:
            fields.append({"column_id": col_summary, "text": summary})
            
        logger.info(f"Logging claim to Slack List {list_id}...")
        
        res = client.slackLists_items_create(
            list_id=list_id,
            initial_fields=fields
        )
        
        if res.get("ok"):
            logger.info("Added claim to Slack List")
            return True
            
    except SlackApiError as exc:
        error_code = exc.response.get("error") if exc.response else None
        if error_code in ("missing_scope", "feature_not_enabled", "method_not_supported"):
            missing = exc.response.get("needed") or "lists:write"
            logger.warning(f"Skipped because of permissions: missing {missing}")
            return False
        logger.error(f"Slack API error during Lists logging: {exc}", exc_info=True)
        return False
    except Exception as exc:
        logger.error(f"Unexpected error during Lists logging: {exc}", exc_info=True)
        return False
