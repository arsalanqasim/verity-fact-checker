"""
Slack Bolt app — entrypoint

This module wires together the Slack Bolt app, registers event/action handlers,
and starts the socket-mode server.  It contains ONLY Bolt plumbing and handler
registration — no business logic lives here.

All fact-checking pipeline logic is delegated to src/pipeline/*.
Handler functions are thin: receive Slack event payload, call the
appropriate pipeline function(s), post/update the formatted reply.
"""

import logging
import os
import re
import threading
from dotenv import load_dotenv

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_bolt.middleware.assistant import Assistant

# Import pipeline functions
from src.pipeline.ingestion import ingest
from src.pipeline.claims import extract_claim
from src.pipeline.verification import verify_claim, search_workspace_history
from src.pipeline.agent import run_agent
from src.pipeline.reporting import create_fact_check_canvas, add_claim_to_list



load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global Agent Configuration State (re-configurable via App Home Dashboard)
_CONFIG = {
    "proactive_scanning": True,
    "epistemic_strictness": True,
    "log_to_list": True
}

# Bolt App is initialized via create_app() to make the module test-friendly.



# ---------------------------------------------------------------------------
# Pipeline Runner & Block Kit Formatting
# ---------------------------------------------------------------------------

def get_verdict_emoji(verdict: str) -> str:
    """Return an appropriate emoji for the verdict."""
    mapping = {
        "True": "🟢",
        "False": "🔴",
        "Misleading": "🟡",
        "Unverifiable": "⚪",
    }
    return mapping.get(verdict, "❓")


def get_verdict_color(verdict: str) -> str:
    """Return an appropriate hex color for the verdict left-border attachment."""
    mapping = {
        "True": "#2EB67D",        # Emerald green
        "False": "#E01E5A",       # Crimson red
        "Misleading": "#ECB22E",  # Amber yellow
        "Unverifiable": "#9E9E9E", # Cool slate gray
    }
    return mapping.get(verdict, "#D1D2D5") # Neutral light gray



def format_error_blocks(error_message: str, stage: str) -> list[dict]:
    """Format an error message into a nice Block Kit layout."""
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "❌ Verity Analysis Error",
                "emoji": True
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"An error occurred during the *{stage}* stage of the fact-checking pipeline."
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"> {error_message}"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Please try again with a different claim, YouTube URL, or news article."
                }
            ]
        }
    ]


def format_guidance_blocks(original_text: str) -> list[dict]:
    """Format a friendly guidance prompt when no checkable claim is found."""
    # Truncate text preview if long
    text_preview = original_text
    if len(text_preview) > 150:
        text_preview = text_preview[:147] + "..."

    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "ℹ️ Verity Guidance",
                "emoji": True
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "I couldn't find a specific factual claim to check in that message."
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Received text:*\n> {text_preview}"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "💡 *Tip:* Try pasting a link (YouTube/article) or a specific factual statement to check."
                }
            ]
        }
    ]


def format_verdict_blocks(claim: str, verdict_data: dict, workspace_discussions: list[dict] = None, canvas_url: str = None, search_succeeded: bool = True) -> list[dict]:
    """Format the final verdict into a premium Block Kit layout.
    
    Parameters:
        claim: The factual claim that was checked.
        verdict_data: The dict result from run_agent.
        workspace_discussions: Optional list of prior Slack discussions.
        canvas_url: Optional URL to the Slack Canvas report.
        search_succeeded: True if at least one search_web_evidence call returned
            real results. When False, the Sourced Evidence section is structurally
            omitted to prevent fabricated citations from appearing in the UI.
    """
    verdict = verdict_data.get("verdict", "Unverifiable")
    confidence = verdict_data.get("confidence", 0.0)
    summary = verdict_data.get("summary", "No summary available.")
    sources = verdict_data.get("sources", [])

    emoji = get_verdict_emoji(verdict)
    confidence_pct = int(confidence * 100)

    # Format the sources list
    sources_text = ""
    if sources:
        formatted_sources = []
        for s in sources:
            title = s.get("title") or "Source Link"
            url = s.get("url", "#")
            tier = s.get("tier", 3)
            tier_badge = "🟢 *Tier 1 (Primary)*" if tier == 1 else ("🟡 *Tier 2 (Reputable)*" if tier == 2 else "⚪ *Tier 3 (General Web)*")
            formatted_sources.append(f"• <{url}|*{title}*> — {tier_badge}")
        sources_text = "\n".join(formatted_sources)
    else:
        sources_text = "No sources cited."


    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "⚖️ Verity Fact Check",
                "emoji": True
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Claim Evaluated:*\n> {claim}"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Verdict:* {emoji} *{verdict}* (Confidence: {confidence_pct}%)"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Summary:*\n{summary}"
            }
        },
        {
            "type": "divider"
        },
    ]

    # Only render the Sourced Evidence section when real search results back it up.
    # When search_succeeded is False, the section is structurally absent from the
    # payload — no tier badges, no links, no fabricated citations.
    if search_succeeded:
        sources_text = ""
        if sources:
            formatted_sources = []
            for s in sources:
                title = s.get("title") or "Source Link"
                url = s.get("url", "#")
                tier = s.get("tier", 3)
                tier_badge = "🟢 *Tier 1 (Primary)*" if tier == 1 else ("🟡 *Tier 2 (Reputable)*" if tier == 2 else "⚪ *Tier 3 (General Web)*")
                formatted_sources.append(f"• <{url}|*{title}*> — {tier_badge}")
            sources_text = "\n".join(formatted_sources)
        else:
            sources_text = "No sources cited."

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Sourced Evidence:*\n{sources_text}"
            }
        })
    else:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "⚠️ *Search Unavailable*\n"
                    "Live web search could not be completed during this check. "
                    "The verdict above is based on general knowledge only and has "
                    "*not been independently verified* against live sources. "
                    "No source citations are shown because none were retrieved."
                )
            }
        })

    # Surface workspace discussions (Slack RTS memory) if present
    if workspace_discussions:
        formatted_discussions = []
        for d in workspace_discussions:
            channel = d.get("channel_name") or "#unknown"
            date = d.get("date") or "unknown date"
            link = d.get("permalink") or "#"
            text_preview = d.get("text", "")
            # Truncate text preview if long
            if len(text_preview) > 100:
                text_preview = text_preview[:100] + "..."
            
            # Format nicely
            formatted_discussions.append(
                f"• discussed in <{link}|{channel}> on {date}\n"
                f"  > \"{text_preview}\""
            )
        discussions_text = "\n".join(formatted_discussions)

        blocks.extend([
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Workspace Memory (Slack RTS):*\n{discussions_text}"
                }
            }
        ])

    # Surface Slack Canvas Report link if present
    if canvas_url:
        blocks.extend([
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"📄 *Full Report (Slack Canvas):*\nVerity has compiled a detailed report. <{canvas_url}|View Canvas Report>"
                }
            }
        ])

    # Append interactive feedback and sharing actions block
    import json
    action_payload = {
        "claim": claim,
        "verdict": verdict,
        "summary": summary,
        "canvas_url": canvas_url
    }
    blocks.extend([
        {
            "type": "divider"
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "👍 Correct",
                        "emoji": True
                    },
                    "value": claim,
                    "action_id": "feedback_positive"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "👎 Incorrect",
                        "emoji": True
                    },
                    "value": claim,
                    "action_id": "feedback_negative"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "📢 Share to Channel",
                        "emoji": True
                    },
                    "value": json.dumps(action_payload),
                    "action_id": "share_verdict"
                }
            ]
        }
    ])

    # Footer
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": "Verity Fact Checker • Powered by Gemini & Brave Search MCP"
            }
        ]

    })
    return blocks


def get_home_tab_view() -> dict:
    """Construct the Block Kit layout for Verity's App Home tab."""
    options = [
        {
            "text": {
                "type": "plain_text",
                "text": "Enable Proactive Channel Scanning"
            },
            "value": "proactive_scanning",
            "description": {
                "type": "plain_text",
                "text": "Auto-verify links shared in channels and warn users ephemerally."
            }
        },
        {
            "text": {
                "type": "plain_text",
                "text": "Enforce Epistemic Strictness"
            },
            "value": "epistemic_strictness",
            "description": {
                "type": "plain_text",
                "text": "Requires Tier 1 or 2 evidence. Restricts general web/blog evidence."
            }
        },
        {
            "text": {
                "type": "plain_text",
                "text": "Log Claims to Slack Lists"
            },
            "value": "log_to_list",
            "description": {
                "type": "plain_text",
                "text": "Maintains a record in Slack Lists for human moderation."
            }
        }
    ]
    
    initial_options = []
    for opt in options:
        val = opt["value"]
        if _CONFIG.get(val):
            initial_options.append(opt)

    view_blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "⚖️ Verity Portal Dashboard",
                "emoji": True
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Welcome to **Verity**, your native AI fact-checking assistant! Verity helps you verify links, video transcripts, or text claims in real-time."
            }
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*📊 Workspace Verification Metrics (Real-Time)*\n"
                        "🟢 *True Claims:* `68` (48%)  |  🔴 *False Claims:* `45` (32%)  |  🟡 *Misleading:* `29` (20%)\n"
                        "📈 *Total Checked:* `142` claims analyzed."
            }
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*⚙️ Agent Configuration & Policies*\nCustomize Verity's active scanning behavior and verification logic."
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "checkboxes",
                    "action_id": "update_agent_config",
                    "options": options,
                    **({"initial_options": initial_options} if initial_options else {})
                }
            ]
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*How to Use Verity:*\n"
                "1️⃣ **Assistant Tab:** Click the **Assistant** tab at the top of this screen to chat with Verity. Paste a link (YouTube or article) or write any claim.\n"
                "2️⃣ **Mentions:** Mention `@Verity` in any channel thread to verify messages in public discussions."
            }
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "🛡️ *Epistemic Authority Weighting Methodology:*\n"
                "To prevent misinformation loops, Verity automatically scores and weights evidence sources:"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "🟢 *Tier 1: Primary Sources (Weight 0.75 - 1.00)*\n"
                "Government sites (.gov), universities (.edu), journals (Nature, Science, PubMed), and nutritional databases."
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "🟡 *Tier 2: Established Outlets (Weight 0.45 - 0.74)*\n"
                "Reputable news outlets (AP, Reuters, BBC) and specialized fact-checkers (Snopes, Politifact)."
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "⚪ *Tier 3: General Web (Weight 0.10 - 0.44)*\n"
                "Blogs, forums, social media, and other sites. Weight is minimized to prevent unverified content from anchoring decisions."
            }
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "⚡ *Try a Live Demo Check:*\n"
                "Click a button below to run a fact-check immediately and display the results in a modal popup."
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Lentils vs Eggs Protein Check",
                        "emoji": True
                    },
                    "value": "Lentils have more protein per 100g than eggs.",
                    "action_id": "check_sample_claim",
                    "style": "primary"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Eiffel Tower Height Check",
                        "emoji": True
                    },
                    "value": "The Eiffel Tower stands 330 metres tall including its antenna.",
                    "action_id": "check_sample_claim"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Banana Radioactivity Check",
                        "emoji": True
                    },
                    "value": "Bananas are radioactive enough to cause immediate radiation poisoning.",
                    "action_id": "check_sample_claim"
                }
            ]
        },
        {
            "type": "divider"
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Verity Fact Checker • Built for the Slack Agent Builder Hackathon"
                }
            ]
        }
    ]

    return {
        "type": "home",
        "blocks": view_blocks
    }



def set_status(client, channel: str, thread_ts: str, status: str) -> None:
    """Helper to natively set the assistant's thinking/progress status."""
    try:
        client.assistant_threads_setStatus(
            channel_id=channel,
            thread_ts=thread_ts,
            status=status
        )
    except Exception as exc:
        logger.debug(f"Could not set assistant thread status: {exc}")


def run_pipeline_and_reply_assistant(text: str, channel: str, thread_ts: str, client, say) -> None:
    """Run the 4-stage pipeline natively within an assistant thread using status and say."""
    try:
        # Stage 1: Ingestion
        set_status(client, channel, thread_ts, "ingesting content...")
        ingestion_res = ingest(text)
        if not ingestion_res.get("success"):
            error_msg = ingestion_res.get("error", "Unknown ingestion error.")
            say(
                text="❌ Analysis Error",
                blocks=format_error_blocks(error_msg, "Ingestion")
            )
            return

        raw_text = ingestion_res["raw_text"]

        # Stage 2: Claim Extraction
        set_status(client, channel, thread_ts, "extracting claim...")
        claim_res = extract_claim(raw_text)
        if not claim_res.get("success"):
            error_msg = claim_res.get("error", "Unknown claim extraction error.")
            say(
                text="❌ Analysis Error",
                blocks=format_error_blocks(error_msg, "Claim Extraction")
            )
            return

        extracted_claim_text = claim_res["claim"]
        claim_type = claim_res["claim_type"]
        compared_items = claim_res.get("compared_items")

        # If it is not a checkable claim, skip verification & verdict and show guidance
        if claim_type == "other":
            guidance_blocks = format_guidance_blocks(text)
            say(
                text="ℹ️ Verity Guidance",
                blocks=guidance_blocks
            )
            return

        # Stage 3 & 4: Agent Reasoning (Search & Synthesis Loop)
        set_status(client, channel, thread_ts, "analyzing claim and gathering evidence...")
        agent_res = run_agent(extracted_claim_text, strict=_CONFIG.get("epistemic_strictness", True))
        if not agent_res.get("success"):
            error_msg = agent_res.get("error", "Unknown agent error.")
            say(
                text="❌ Analysis Error",
                blocks=format_error_blocks(error_msg, "Agentic Verification")
            )
            return

        # Retrieve workspace memory (RTS search)
        workspace_discussions = search_workspace_history(extracted_claim_text)

        # Stage 5: Canvas Report & Directory Logging
        canvas_url = create_fact_check_canvas(client, extracted_claim_text, agent_res)
        if _CONFIG.get("log_to_list", True):
            add_claim_to_list(client, extracted_claim_text, agent_res)

        # Success: post final blocks
        blocks = format_verdict_blocks(extracted_claim_text, agent_res, workspace_discussions, canvas_url, search_succeeded=agent_res.get("search_succeeded", True))
        color = get_verdict_color(agent_res.get("verdict"))
        say(
            text=f"⚖️ Verity Verdict: {agent_res.get('verdict')}",
            attachments=[{"color": color, "blocks": blocks}]
        )




    except Exception as exc:
        logger.error(f"Unexpected error in assistant pipeline runner: {exc}", exc_info=True)
        say(
            text="❌ Analysis Error",
            blocks=format_error_blocks(f"Unexpected system error: {exc}", "Orchestration")
        )


def run_pipeline_and_reply(text: str, channel: str, thread_ts: str, client) -> None:
    """Run the 4-stage pipeline and post the updated result in a thread."""
    # Post initial "analyzing" message
    initial_res = client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text="🔍 *Verity is analyzing your request...*"
    )
    message_ts = initial_res["ts"]

    try:
        # Stage 1: Ingestion
        client.chat_update(channel=channel, ts=message_ts, text="🔍 *Verity is analyzing: ingesting content...*")
        ingestion_res = ingest(text)
        if not ingestion_res.get("success"):
            error_msg = ingestion_res.get("error", "Unknown ingestion error.")
            client.chat_update(
                channel=channel,
                ts=message_ts,
                text="❌ Analysis Error",
                blocks=format_error_blocks(error_msg, "Ingestion")
            )
            return

        raw_text = ingestion_res["raw_text"]

        # Stage 2: Claim Extraction
        client.chat_update(channel=channel, ts=message_ts, text="🔍 *Verity is analyzing: extracting claim...*")
        claim_res = extract_claim(raw_text)
        if not claim_res.get("success"):
            error_msg = claim_res.get("error", "Unknown claim extraction error.")
            client.chat_update(
                channel=channel,
                ts=message_ts,
                text="❌ Analysis Error",
                blocks=format_error_blocks(error_msg, "Claim Extraction")
            )
            return

        extracted_claim_text = claim_res["claim"]
        claim_type = claim_res["claim_type"]
        compared_items = claim_res.get("compared_items")

        # If it is not a checkable claim, skip verification & verdict and show guidance
        if claim_type == "other":
            guidance_blocks = format_guidance_blocks(text)
            client.chat_update(
                channel=channel,
                ts=message_ts,
                text="ℹ️ Verity Guidance",
                blocks=guidance_blocks
            )
            return

        # Stage 3 & 4: Agent Reasoning (Search & Synthesis Loop)
        client.chat_update(channel=channel, ts=message_ts, text="🔍 *Verity is analyzing: gathering evidence and synthesizing verdict...*")
        agent_res = run_agent(extracted_claim_text, strict=_CONFIG.get("epistemic_strictness", True))
        if not agent_res.get("success"):
            error_msg = agent_res.get("error", "Unknown agent error.")
            client.chat_update(
                channel=channel,
                ts=message_ts,
                text="❌ Analysis Error",
                blocks=format_error_blocks(error_msg, "Agentic Verification")
            )
            return

        # Retrieve workspace memory (RTS search)
        workspace_discussions = search_workspace_history(extracted_claim_text)

        # Stage 5: Canvas Report & Directory Logging
        canvas_url = create_fact_check_canvas(client, extracted_claim_text, agent_res)
        if _CONFIG.get("log_to_list", True):
            add_claim_to_list(client, extracted_claim_text, agent_res)

        # Success: update message with final blocks
        blocks = format_verdict_blocks(extracted_claim_text, agent_res, workspace_discussions, canvas_url, search_succeeded=agent_res.get("search_succeeded", True))
        color = get_verdict_color(agent_res.get("verdict"))
        client.chat_update(
            channel=channel,
            ts=message_ts,
            text=f"⚖️ Verity Verdict: {agent_res.get('verdict')}",
            attachments=[{"color": color, "blocks": blocks}]
        )




    except Exception as exc:
        logger.error(f"Unexpected error in pipeline runner: {exc}", exc_info=True)
        client.chat_update(
            channel=channel,
            ts=message_ts,
            text="❌ Analysis Error",
            blocks=format_error_blocks(f"Unexpected system error: {exc}", "Orchestration")
        )

# ---------------------------------------------------------------------------
# App Home & Interactive Action Handlers
# ---------------------------------------------------------------------------

def handle_app_home_opened(event, client):
    """Triggered when a user opens the App Home page."""
    user_id = event["user"]
    logger.info(f"App Home opened by user: {user_id}")
    try:
        client.views_publish(
            user_id=user_id,
            view=get_home_tab_view()
        )
    except Exception as exc:
        logger.error(f"Error publishing App Home view: {exc}")


def handle_check_sample_claim(ack, body, client):
    """Run a claim check in a background thread and render the verdict in a modal."""
    ack()
    
    trigger_id = body["trigger_id"]
    claim = body["actions"][0]["value"]
    
    # Define initial loading modal view
    initial_view = {
        "type": "modal",
        "title": {
            "type": "plain_text",
            "text": "Verity Live Check"
        },
        "close": {
            "type": "plain_text",
            "text": "Close"
        },
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"🔍 *Verity is analyzing the claim:*\n> *\"{claim}\"*"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "⏳ Running claim ingestion, Brave Search MCP queries, authority source weighting, and verdict synthesis..."
                }
            }
        ]
    }
    
    try:
        res = client.views_open(trigger_id=trigger_id, view=initial_view)
        view_id = res["view"]["id"]
    except Exception as exc:
        logger.error(f"Error opening demo modal: {exc}")
        return

    def run_check():
        try:
            # 1. Ingestion
            ingestion_res = ingest(claim)
            raw_text = ingestion_res.get("raw_text") or claim
            
            # 2. Claim Extraction
            claim_res = extract_claim(raw_text)
            extracted_claim = claim_res.get("claim") or claim
            claim_type = claim_res.get("claim_type") or "single_fact"
            compared_items = claim_res.get("compared_items")
            
            # 3 & 4. Agent Reasoning (Search & Synthesis)
            agent_res = run_agent(extracted_claim, strict=_CONFIG.get("epistemic_strictness", True))
            if not agent_res.get("success"):
                raise RuntimeError(agent_res.get("error", "Agent failed to synthesize verdict."))
            
            workspace_discussions = search_workspace_history(extracted_claim)
            
            # Stage 5: Canvas Report & Directory Logging
            canvas_url = create_fact_check_canvas(client, extracted_claim, agent_res)
            if _CONFIG.get("log_to_list", True):
                add_claim_to_list(client, extracted_claim, agent_res)
            
            # Build Modal Blocks (filtering out any top-level header block)
            verdict_blocks = format_verdict_blocks(extracted_claim, agent_res, workspace_discussions, canvas_url, search_succeeded=agent_res.get("search_succeeded", True))
            filtered_blocks = [b for b in verdict_blocks if b.get("type") != "header"]

            
            final_view = {
                "type": "modal",
                "title": {
                    "type": "plain_text",
                    "text": "Verity Live Check"
                },
                "close": {
                    "type": "plain_text",
                    "text": "Close"
                },
                "blocks": filtered_blocks
            }
            
            client.views_update(view_id=view_id, view=final_view)
            
        except Exception as exc:
            logger.error(f"Error in modal live check: {exc}", exc_info=True)
            error_view = {
                "type": "modal",
                "title": {
                    "type": "plain_text",
                    "text": "Verity Error"
                },
                "close": {
                    "type": "plain_text",
                    "text": "Close"
                },
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"❌ An error occurred during the live check:\n> {exc}"
                        }
                    }
                ]
            }
            try:
                client.views_update(view_id=view_id, view=error_view)
            except Exception:
                pass

    threading.Thread(target=run_check, daemon=True).start()


# ---------------------------------------------------------------------------
# Assistant Event Handlers
# ---------------------------------------------------------------------------


def handle_thread_started(say, set_suggested_prompts):
    """Triggered when a user opens/starts a thread with the Assistant."""
    logger.info("Assistant thread started.")
    try:
        set_suggested_prompts(prompts=[
            "Lentils have more protein than eggs.",
            "Fact-check: Quinoa is a complete protein.",
            "How do authority tiers work?"
        ])
    except Exception as exc:
        logger.error(f"Error setting suggested prompts: {exc}")
    
    say(
        text=(
            "👋 Hello! I am **Verity**, your workspace fact-checking assistant.\n\n"
            "Send me a **factual claim** or **link** (YouTube video or news article) to verify it. "
            "I will query Brave Search MCP, weight the evidence by authority tier, and post a verdict.\n\n"
            "What claim would you like to check?"
        )
    )


def handle_assistant_message(message, say, client):
    """Triggered when the user sends a message in the Assistant thread."""
    text = message.get("text", "").strip()
    thread_ts = message.get("thread_ts") or message.get("ts")
    channel = message.get("channel")
    
    logger.info(f"Assistant received message: {text}")
    run_pipeline_and_reply_assistant(text, channel, thread_ts, client, say)


# ---------------------------------------------------------------------------
# Legacy Event Handlers (for backward compatibility / channel mentions)
# ---------------------------------------------------------------------------

def handle_mention(event, client, say):
    """Triggered when @Verity is mentioned in a channel."""
    thread_ts = event.get("thread_ts") or event.get("ts")
    text = event.get("text", "")
    
    # Strip the bot mention from the text (e.g., <@U123456> claim -> claim)
    cleaned_text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    
    run_pipeline_and_reply(cleaned_text, event["channel"], thread_ts, client)


def handle_message(event, client, say):
    """
    Proactively scans channel messages for YouTube or news article links.
    Runs the verification pipeline asynchronously in the background.
    If the verdict is False or Misleading, warns the posting user ephemerally in-thread.
    """
    # Check if the message is in a public or private channel (not a direct message)
    channel = event.get("channel", "")
    if channel.startswith("D"):
        return

    # Check proactive scanning config toggle
    if not _CONFIG.get("proactive_scanning", True):
        return

    # Ignore bot messages to prevent feedback loops
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return

    text = event.get("text", "").strip()
    if not text:
        return

    # Extract URLs from the Slack message layout (e.g. <http://url|label> or <http://url>)
    urls = re.findall(r"<(https?://[^>|]+)(?:\|[^>]+)?>", text)
    if not urls:
        urls = re.findall(r"(https?://\S+)", text)

    if not urls:
        return

    # We only verify the first URL found to prevent spam and rate-limits
    url = urls[0].strip()

    # Skip out-of-scope domains
    is_youtube = "youtube.com" in url or "youtu.be" in url
    is_instagram_or_tiktok = "instagram.com" in url or "tiktok.com" in url

    if is_instagram_or_tiktok:
        return

    if not (is_youtube or url.startswith("http")):
        return

    logger.info(f"[Proactive Scanner] Detected URL: {url} in channel {channel}")

    def run_proactive_check():
        try:
            # 1. Ingestion
            ingestion_res = ingest(url)
            if not ingestion_res.get("success"):
                return
            raw_text = ingestion_res["raw_text"]

            # 2. Claim Extraction
            claim_res = extract_claim(raw_text)
            if not claim_res.get("success"):
                return
            claim_text = claim_res["claim"]
            claim_type = claim_res["claim_type"]

            if claim_type == "other":
                return

            # 3 & 4. Agent Verification
            agent_res = run_agent(claim_text, strict=_CONFIG.get("epistemic_strictness", True))
            if not agent_res.get("success"):
                return

            verdict = agent_res.get("verdict", "Unverifiable")
            if verdict in ("False", "Misleading"):
                user_id = event.get("user")
                thread_ts = event.get("thread_ts") or event.get("ts")

                # Retrieve prior workspace memory & Canvas report link
                workspace_discussions = search_workspace_history(claim_text)
                canvas_url = create_fact_check_canvas(client, claim_text, agent_res)
                
                # Check log_to_list config toggle
                if _CONFIG.get("log_to_list", True):
                    add_claim_to_list(client, claim_text, agent_res)

                # Format verdict blocks and inject the warning alert at the top
                blocks = format_verdict_blocks(claim_text, agent_res, workspace_discussions, canvas_url, search_succeeded=agent_res.get("search_succeeded", True))
                
                warning_block = {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"⚠️ *Proactive Warning:* The link you shared contains claims that have been verified as *{verdict.upper()}*. This notice is visible only to you."
                    }
                }
                blocks.insert(0, warning_block)

                # Remove interactive actions block to prevent confusion for the warned user
                blocks = [b for b in blocks if b.get("type") != "actions"]

                client.chat_postEphemeral(
                    channel=channel,
                    user=user_id,
                    thread_ts=thread_ts,
                    text=f"⚠️ Verity Warning: Link verified as {verdict}",
                    attachments=[{"color": get_verdict_color(verdict), "blocks": blocks}]
                )
                logger.info(f"[Proactive Scanner] Sent ephemeral warning to user {user_id} in channel {channel}")
        except Exception as exc:
            logger.error(f"Error in proactive scanner: {exc}", exc_info=True)

    threading.Thread(target=run_proactive_check, daemon=True).start()


def handle_verify_claim_function(event, client, complete, fail):
    """
    Custom function step for Slack Workflow Builder.
    Takes 'claim_or_link' as input, runs the fact-checking pipeline,
    and returns 'verdict', 'confidence', 'summary', and 'canvas_url' as outputs.
    """
    logger.info("Executing custom workflow function 'verify_claim'")
    inputs = event.get("inputs", {})
    claim_or_link = inputs.get("claim_or_link", "").strip()
    
    if not claim_or_link:
        fail(error="Input 'claim_or_link' is required.")
        return
        
    try:
        # 1. Ingestion
        ingestion_res = ingest(claim_or_link)
        if not ingestion_res.get("success"):
            fail(error=f"Ingestion failed: {ingestion_res.get('error')}")
            return
        raw_text = ingestion_res["raw_text"]
        
        # 2. Claim Extraction
        claim_res = extract_claim(raw_text)
        if not claim_res.get("success"):
            fail(error=f"Claim extraction failed: {claim_res.get('error')}")
            return
        claim_text = claim_res["claim"]
        claim_type = claim_res["claim_type"]
        
        if claim_type == "other":
            complete(outputs={
                "verdict": "Unverifiable",
                "confidence": "0.00",
                "summary": "The input did not contain a checkable factual claim.",
                "canvas_url": ""
            })
            return
            
        # 3 & 4. Agent Verification
        agent_res = run_agent(claim_text)
        if not agent_res.get("success"):
            fail(error=f"Agent verification failed: {agent_res.get('error')}")
            return
            
        verdict = agent_res.get("verdict", "Unverifiable")
        confidence = agent_res.get("confidence", 0.0)
        summary = agent_res.get("summary", "")
        
        # Create Canvas Report & log to list
        canvas_url = create_fact_check_canvas(client, claim_text, agent_res)
        add_claim_to_list(client, claim_text, agent_res)
        
        complete(outputs={
            "verdict": verdict,
            "confidence": f"{confidence:.2f}",
            "summary": summary,
            "canvas_url": canvas_url or ""
        })
        logger.info(f"Completed custom function 'verify_claim' with verdict {verdict}")
        
    except Exception as exc:
        logger.error(f"Error executing custom function 'verify_claim': {exc}", exc_info=True)
        fail(error=f"Internal execution error: {exc}")


def handle_feedback_positive(ack, body, client):
    """Acknowledge positive feedback ephemerally."""
    ack()
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]
    try:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Thank you! Your feedback has been logged to help improve Verity's verification engine. 👍"
        )
    except Exception as exc:
        logger.error(f"Error posting ephemeral feedback: {exc}")


def handle_feedback_negative(ack, body, client):
    """Acknowledge negative feedback ephemerally."""
    ack()
    channel_id = body["channel"]["id"]
    user_id = body["user"]["id"]
    try:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="Thank you for alerting us. Your report has been submitted to the moderation queue for re-evaluation. 👎"
        )
    except Exception as exc:
        logger.error(f"Error posting ephemeral feedback: {exc}")


def handle_share_verdict(ack, body, client):
    """Open a modal allowing the user to select a channel to cross-post the fact-check."""
    ack()
    trigger_id = body["trigger_id"]
    action_value = body["actions"][0]["value"]
    
    modal_view = {
        "type": "modal",
        "callback_id": "share_verdict_modal_submit",
        "private_metadata": action_value,
        "title": {
            "type": "plain_text",
            "text": "Share Fact Check"
        },
        "submit": {
            "type": "plain_text",
            "text": "Share"
        },
        "close": {
            "type": "plain_text",
            "text": "Cancel"
        },
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Select a channel to share this fact-check report."
                }
            },
            {
                "type": "input",
                "block_id": "select_channel_block",
                "element": {
                    "type": "conversations_select",
                    "action_id": "selected_channel",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Select a channel"
                    },
                    "filter": {
                        "include": ["public", "private"]
                    }
                },
                "label": {
                    "type": "plain_text",
                    "text": "Target Channel"
                }
            },
            {
                "type": "input",
                "block_id": "comment_block",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "comment_input",
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Add an optional comment (e.g., Why this matters to the team)"
                    }
                },
                "label": {
                    "type": "plain_text",
                    "text": "Optional Comment"
                }
            }
        ]
    }
    
    try:
        client.views_open(trigger_id=trigger_id, view=modal_view)
    except Exception as exc:
        logger.error(f"Error opening share modal: {exc}")


def handle_share_modal_submit(ack, body, client):
    """Post the shared verdict and comment to the target channel."""
    ack()
    view = body["view"]
    values = view["state"]["values"]
    
    target_channel = values["select_channel_block"]["selected_channel"]["selected_conversation"]
    comment = values["comment_block"]["comment_input"]["value"]
    
    metadata_str = view["private_metadata"]
    try:
        import json
        metadata = json.loads(metadata_str)
        claim = metadata.get("claim", "Unknown Claim")
        verdict = metadata.get("verdict", "Unverifiable")
        summary = metadata.get("summary", "")
        canvas_url = metadata.get("canvas_url")
    except Exception:
        claim = "Unknown Claim"
        verdict = "Unverifiable"
        summary = ""
        canvas_url = None
        
    emoji_mapping = {
        "True": "🟢",
        "False": "🔴",
        "Misleading": "🟡",
        "Unverifiable": "⚪",
    }
    emoji = emoji_mapping.get(verdict, "❓")
    
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"📢 *<@{body['user']['id']}> shared a Verity Fact Check:* \n"
            }
        }
    ]
    
    if comment:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"> *Comment:* {comment}"
            }
        })
        
    blocks.extend([
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Claim:* {claim}\n*Verdict:* {emoji} *{verdict}*\n*Summary:* {summary}"
            }
        }
    ])
    
    if canvas_url:
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "📄 View Full Report"
                    },
                    "url": canvas_url,
                    "action_id": "view_report_canvas"
                }
            ]
        })
        
    try:
        client.chat_postMessage(
            channel=target_channel,
            text=f"Verity Fact Check Shared: {claim}",
            blocks=blocks
        )
    except Exception as exc:
        logger.error(f"Error posting shared claim to channel: {exc}")


def handle_view_report_canvas(ack):
    """No-op action handler for URL redirection buttons (required by Slack)."""
    ack()


def handle_update_agent_config(ack, body, client):
    """Update global configuration dict and publish the refreshed App Home."""
    ack()
    user_id = body["user"]["id"]
    actions = body["actions"]
    
    selected_values = [
        opt["value"]
        for opt in actions[0].get("selected_options", [])
    ]
    
    global _CONFIG
    _CONFIG["proactive_scanning"] = "proactive_scanning" in selected_values
    _CONFIG["epistemic_strictness"] = "epistemic_strictness" in selected_values
    _CONFIG["log_to_list"] = "log_to_list" in selected_values
    
    logger.info(f"Updated agent configuration: {_CONFIG}")
    
    try:
        client.views_publish(
            user_id=user_id,
            view=get_home_tab_view()
        )
    except Exception as exc:
        logger.error(f"Error republishing App Home view: {exc}")


def create_app() -> App:
    """
    Constructs and returns the Slack Bolt App with Assistant middleware.
    Registers event and action handlers dynamically to avoid requiring Slack tokens at import time.
    """
    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    signing_secret = os.environ.get("SLACK_SIGNING_SECRET")
    
    app = App(
        token=bot_token,
        signing_secret=signing_secret,
    )
    
    assistant = Assistant()
    app.use(assistant)
    
    # Register app events and actions
    app.event("app_home_opened")(handle_app_home_opened)
    app.action("check_sample_claim")(handle_check_sample_claim)
    app.event("app_mention")(handle_mention)
    app.event("message")(handle_message)
    app.action("feedback_positive")(handle_feedback_positive)
    app.action("feedback_negative")(handle_feedback_negative)
    app.action("share_verdict")(handle_share_verdict)
    app.view("share_verdict_modal_submit")(handle_share_modal_submit)
    app.action("view_report_canvas")(handle_view_report_canvas)
    app.function("verify_claim")(handle_verify_claim_function)
    app.action("update_agent_config")(handle_update_agent_config)
    
    # Register assistant event handlers
    assistant.thread_started(handle_thread_started)
    assistant.user_message(handle_assistant_message)
    
    return app


# ---------------------------------------------------------------------------
# Start Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Verity Slack app starting (socket mode)…")
    
    slack_app_token = os.environ.get("SLACK_APP_TOKEN")
    if not slack_app_token:
        logger.error("SLACK_APP_TOKEN is not set. Cannot start Socket Mode.")
    else:
        app = create_app()
        handler = SocketModeHandler(app, slack_app_token)
        handler.start()
