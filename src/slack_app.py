"""
Slack Bolt app — entrypoint

This module wires together the Slack Bolt app, registers event/action handlers,
and starts the socket-mode server.  It contains ONLY Bolt plumbing and handler
registration — no business logic lives here.

All fact-checking pipeline logic is delegated to src/pipeline/*.
Handler functions should be thin: receive Slack event payload, call the
appropriate pipeline function(s), post the formatted reply.
"""

import logging
import os

from dotenv import load_dotenv

# Bolt imports — will be used once handlers are implemented (Phase 1+)
# from slack_bolt import App
# from slack_bolt.adapter.socket_mode import SocketModeHandler

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App initialisation — uncomment once SLACK_BOT_TOKEN / SLACK_SIGNING_SECRET
# are available in the environment.
# ---------------------------------------------------------------------------
# app = App(
#     token=os.environ["SLACK_BOT_TOKEN"],
#     signing_secret=os.environ["SLACK_SIGNING_SECRET"],
# )


# ---------------------------------------------------------------------------
# Event handlers — stubs only, no business logic yet.
# ---------------------------------------------------------------------------

# @app.event("message")
# def handle_message(event, say, client):
#     """Triggered on any message the bot can see.  Will route to pipeline."""
#     pass

# @app.event("app_mention")
# def handle_mention(event, say, client):
#     """Triggered when @Verity is mentioned in a channel."""
#     pass


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Verity Slack app starting (socket mode)…")
    # handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    # handler.start()
    logger.info(
        "App not yet started — uncomment the SocketModeHandler block once "
        "env vars are configured."
    )
