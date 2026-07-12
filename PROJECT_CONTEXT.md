# Verity — Project Context (for coding agent)

Read this file in full before writing any code. This is the durable source of truth for the project — refer back to it every session, not just once.

## What we're building
A Slack agent (hackathon: Slack Agent Builder Challenge, "Slack Agent for Good" track) that takes a pasted link or plain text claim and returns a sourced, source-quality-weighted verdict: True / False / Misleading / Unverifiable, posted as a threaded Slack reply.

## Non-negotiable constraints
- **Win the hackathon** is the top priority. Working, demoable code beats elegant, incomplete code.
- The MVP demo MUST work live and reliably. Do not build fragile ingestion paths into the critical path — see input priority below.
- Deadline: July 13, 2026, 5pm PDT. Submission needs: text description, ~3 min demo video, architecture diagram, sandbox URL.

## Input priority (build and test in this order)
1. Plain pasted text/claim — no ingestion risk, build and prove the pipeline end-to-end on this FIRST. STATUS: implemented, tested (12 tests, all passing).
2. YouTube video link — use `youtube-transcript-api`. STATUS: implemented, tested against a real video with real captions.
3. Article/news link — use `trafilatura`. STATUS: implemented, tested against a real Wikipedia article.
4. Instagram Reel link — **DECIDED: OUT OF SCOPE for MVP, not a stretch goal, do not attempt further integration.**

### Instagram decision — final, not open for reconsideration mid-build
Feasibility spike (2026-07-10, `scripts/ig_spike.py`) confirmed via yt-dlp against 3 real public Reels: video/audio download works (3/3, ~2.5s each), but Instagram exposes **no transcript or caption API of any kind** — not creator-provided, not auto-generated. This is confirmed by yt-dlp's own issue tracker (yt-dlp/yt-dlp#15874), not just our own test. Getting a spoken-word transcript would require downloading audio + running Whisper STT, adding ~10-30s latency and a ~2GB model dependency not in the current stack. The poster's text caption is available but is not a reliable stand-in for the spoken claim (often vague/hashtag-driven). yt-dlp's Instagram extractor has also broken and been silently patched multiple times over the past year — no SLA, real risk of a live-demo failure on an unfamiliar network (e.g. a judge's).

**Consequence for the build:** `ingestion.py` already returns a clean out-of-scope error for Instagram/TikTok URLs — this is correct and final, not a placeholder. Do not add Whisper, audio download, or any Instagram-specific extraction code during this hackathon. If asked, roadmap language is: "tested and understood, scoped out deliberately to protect demo reliability, clear integration path documented for post-hackathon."

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
- **Gemini API (Google AI Studio, free tier) for claim extraction and verdict synthesis** — model: `gemini-3.1-flash-lite`. Use structured JSON output via `response_mime_type="application/json"` + `response_schema`, no free-text parsing.
- MCP client integration for Brave Search MCP server (verification)
- `youtube-transcript-api` for YouTube ingestion
- `trafilatura` for article text extraction
- pytest for tests — every pipeline module needs a unit test with a fixed input/output before it's considered done

Note: free tier data may be used by Google to improve their models. Not a concern for this project (claim text is public content being fact-checked, not sensitive user data), but don't route anything private through it.

## Repo conventions
- One module per pipeline stage/component under `src/pipeline/` (`ingestion.py`, `claims.py`, `verification.py`, `mcp_client.py`, `reporting.py`, `agent.py`)
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
GEMINI_API_KEY=
BRAVE_SEARCH_MCP_URL=
```

## Definition of done for MVP
- Paste a plain text claim in Slack → agent replies in-thread with verdict + sources, within a reasonable time (state actual latency once measured).
- Paste a YouTube link → same result, using transcript ingestion.
- Paste an article link → same result.
- Architecture diagram accurately reflects what was actually built (not the aspirational version).
