# Verity — Project Context (for coding agent)

Read this file in full before writing any code. This is the durable source of truth for the project — refer back to it every session, not just once.

## What we're building
A Slack agent (hackathon: Slack Agent Builder Challenge, "Slack Agent for Good" track) that takes a pasted link or plain text claim and returns a sourced, source-quality-weighted verdict: True / False / Misleading / Unverifiable, posted as a threaded Slack reply.

## Non-negotiable constraints
- **Win the hackathon** is the top priority. Working, demoable code beats elegant, incomplete code.
- The MVP demo MUST work live and reliably. Do not build fragile ingestion paths into the critical path — see input priority below.
- Deadline: July 13, 2026, 5pm PDT. Submission needs: text description, ~3 min demo video, architecture diagram, sandbox URL.

## Input priority (build and test in this order)
1. Plain pasted text/claim — no ingestion risk, build and prove the pipeline end-to-end on this FIRST.
2. YouTube video link — use `youtube-transcript-api` or official captions; reliable.
3. Article/news link — use a text-extraction library (e.g. `trafilatura` or `newspaper3k`).
4. (Stretch, isolated experiment, NOT on critical path) Instagram Reel link — test feasibility in total isolation before integrating. If unreliable, it is dropped from the live demo and mentioned only as roadmap.

## Corrected technology mapping (do not use RTS as a web search substitute)
- **MCP server integration (core)** — external verification via a web-search MCP server (Brave Search MCP to start). This is the actual fact-finding mechanism.
- **RTS API (secondary)** — Slack's in-workspace search. Use ONLY to check if a claim was already discussed in this workspace before running external verification. It cannot and must not be used to search the internet.
- **Slack AI capabilities** — response formatting / Block Kit delivery of the verdict, threaded reply.

## Pipeline stages (build as separate, independently testable modules)
1. **Ingestion** — detect input type, route to correct extractor, return raw text/transcript.
2. **Claim extraction** — identify the specific checkable claim(s) from raw text via LLM call. Must correctly classify claim type (e.g. comparative/superlative claims like "X has more protein than Y and Z" need to be checked as a ranking claim, not a single fact).
3. **Verification** — query the web-search MCP server for evidence. Rank/weight sources by authority (prioritize .gov/.edu/peer-reviewed/primary sources over generic content/blogs) — this ranking logic is a named, deliberate design decision, not a default pass-through of raw search results.
4. **Verdict synthesis** — LLM call producing verdict + confidence + cited sources in structured JSON.
5. **Slack delivery** — Bolt app posts formatted threaded reply using Block Kit.

## Tech stack
- Python 3.11+, Slack Bolt SDK for Python
- Claude API (Anthropic) for claim extraction and verdict synthesis — use structured JSON output, no free-text parsing
- MCP client integration for Brave Search MCP server (verification)
- `youtube-transcript-api` for YouTube ingestion
- `trafilatura` for article text extraction
- pytest for tests — every pipeline module needs a unit test with a fixed input/output before it's considered done

## Repo conventions
- One module per pipeline stage under `src/pipeline/` (`ingestion.py`, `claims.py`, `verification.py`, `verdict.py`)
- `src/slack_app.py` — Bolt app entrypoint, event handlers only, no business logic
- `tests/` mirrors `src/pipeline/`
- Commit after each working stage, not one giant commit — judges/teammates should be able to see incremental, real progress in git history
- `.env.example` committed with required variable names but no real secrets; `.env` gitignored
- `README.md` documents setup steps for a teammate starting fresh (Slack app manifest, required scopes, env vars, how to run locally)

## Environment variables needed
```
SLACK_BOT_TOKEN=
SLACK_SIGNING_SECRET=
SLACK_APP_TOKEN=
ANTHROPIC_API_KEY=
BRAVE_SEARCH_MCP_URL=
```

## Definition of done for MVP
- Paste a plain text claim in Slack → agent replies in-thread with verdict + sources, within a reasonable time (state actual latency once measured).
- Paste a YouTube link → same result, using transcript ingestion.
- Paste an article link → same result.
- Architecture diagram accurately reflects what was actually built (not the aspirational version).
