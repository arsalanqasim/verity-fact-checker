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
from dotenv import load_dotenv

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# Import pipeline functions
from src.pipeline.ingestion import ingest
from src.pipeline.claims import extract_claim
from src.pipeline.verification import verify_claim
from src.pipeline.verdict import synthesise_verdict

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Bolt App
app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
)

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


def format_verdict_blocks(claim: str, verdict_data: dict, workspace_discussions: list[dict] = None) -> list[dict]:
    """Format the final verdict into a premium Block Kit layout."""
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
            formatted_sources.append(f"• <{url}|{title}> (Tier {tier})")
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
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Sourced Evidence:*\n{sources_text}"
            }
        }
    ]

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

        # Stage 3: Verification
        client.chat_update(channel=channel, ts=message_ts, text="🔍 *Verity is analyzing: searching for evidence...*")
        verification_res = verify_claim(extracted_claim_text, claim_type, compared_items)
        if not verification_res.get("success"):
            error_msg = verification_res.get("error", "Unknown verification error.")
            client.chat_update(
                channel=channel,
                ts=message_ts,
                text="❌ Analysis Error",
                blocks=format_error_blocks(error_msg, "Verification")
            )
            return

        evidence = verification_res["evidence"]
        workspace_discussions = verification_res.get("workspace_discussions", [])

        # Stage 4: Verdict Synthesis
        client.chat_update(channel=channel, ts=message_ts, text="🔍 *Verity is analyzing: synthesizing verdict...*")
        verdict_res = synthesise_verdict(extracted_claim_text, evidence)
        if not verdict_res.get("success"):
            error_msg = verdict_res.get("error", "Unknown verdict synthesis error.")
            client.chat_update(
                channel=channel,
                ts=message_ts,
                text="❌ Analysis Error",
                blocks=format_error_blocks(error_msg, "Verdict Synthesis")
            )
            return

        # Success: update message with final blocks
        blocks = format_verdict_blocks(extracted_claim_text, verdict_res, workspace_discussions)
        client.chat_update(
            channel=channel,
            ts=message_ts,
            text=f"⚖️ Verity Verdict: {verdict_res.get('verdict')}",
            blocks=blocks
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
# Event Handlers
# ---------------------------------------------------------------------------

@app.event("app_mention")
def handle_mention(event, client, say):
    """Triggered when @Verity is mentioned in a channel."""
    thread_ts = event.get("thread_ts") or event.get("ts")
    text = event.get("text", "")
    
    # Strip the bot mention from the text (e.g., <@U123456> claim -> claim)
    cleaned_text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    
    run_pipeline_and_reply(cleaned_text, event["channel"], thread_ts, client)


@app.event("message")
def handle_message(event, client, say):
    """Triggered on any message the bot can see. Auto-respond only in DMs."""
    # Ignore messages from bots/subtypes to prevent loops
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return

    channel = event.get("channel")
    channel_type = event.get("channel_type")

    # Respond automatically only if it is a DM
    is_dm = channel_type == "im" or (channel and channel.startswith("D"))
    if is_dm:
        text = event.get("text", "")
        thread_ts = event.get("thread_ts") or event.get("ts")
        run_pipeline_and_reply(text, channel, thread_ts, client)


# ---------------------------------------------------------------------------
# Start Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Verity Slack app starting (socket mode)…")
    
    slack_app_token = os.environ.get("SLACK_APP_TOKEN")
    if not slack_app_token:
        logger.error("SLACK_APP_TOKEN is not set. Cannot start Socket Mode.")
    else:
        handler = SocketModeHandler(app, slack_app_token)
        handler.start()
