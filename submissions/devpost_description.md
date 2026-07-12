# Verity — Devpost Submission Text Description
## Copy this into the Devpost project description form

---

## Inspiration

Every day, misinformation spreads through social media, YouTube videos, and news headlines — and most people never check it. Not because they don't care, but because verifying a single claim takes 10+ minutes across multiple tabs: search the web, find a credible source, read the study, check the outlet's reputation, repeat. The friction is the problem.

The trigger case for Verity was simple: someone sees an Instagram Reel claiming that a specific food has more protein than chicken *and* eggs. There's no fast way to check that in the moment. By the time most people would verify it, they've already shared it.

**Verity is the fact-check button the internet doesn't have** — one paste, one sourced answer, right inside Slack where your team already shares and discusses content.

---

## What It Does

Verity is a Slack agent that takes a pasted link or plain-text claim and returns a **sourced, source-quality-weighted verdict** — **True / False / Misleading / Unverifiable** — posted as a threaded Slack reply in under 30 seconds.

**Three input types supported:**
- **Plain text claim** — paste any factual statement directly
- **YouTube video link** — Verity fetches the video transcript and checks the spoken claim
- **Article / news link** — Verity extracts the article body and identifies the checkable claim

**What you get back:**
- Verdict with confidence score (0–100%)
- Summary of the key evidence
- Sourced citations with authority tier badges (Tier 1 / Tier 2 / Tier 3)
- A Slack Canvas full report (persists indefinitely)
- An entry in the workspace's Slack Lists claim directory
- Workspace memory — if this claim was previously discussed in Slack, those threads surface automatically

---

## How We Built It

Verity is a 5-stage agentic pipeline built in Python with the Slack Bolt SDK:

### Stage 1 — Ingestion
Detects input type (YouTube URL → youtube-transcript-api; article URL → trafilatura; plain text → passthrough). All failure paths return a safe error dict — no crashes, no ingestion fragility on the demo path.

### Stage 2 — Claim Extraction
Gemini 3.1 Flash Lite identifies the specific *checkable* claim and classifies its type: single_fact, comparative (e.g., "X has more protein than Y and Z"), or causal. Comparative claims are classified distinctly so they aren't collapsed into a single-fact check, and the agent is prompted to investigate each compared entity separately.

### Stage 3 — Agentic Verification Loop (MCP Integration)
Gemini autonomously formulates search queries and calls the **Brave Search MCP server** via SSE transport. Key safety features:
- **Hard 4-turn cap** — prevents runaway agentic loops
- **Deduplication guard** — identical queries are short-circuited with a synthesis nudge
- **No Automatic Function Calling** — we use a manual tool loop to maintain full observability

### Stage 4 — Verdict Synthesis
A separate structured synthesis turn (tools disabled, response_schema enforced) produces a typed JSON verdict: { verdict, confidence, summary, sources[] }.

**Citation hallucination guard:** A whitelist of every URL returned by Brave Search is passed to the synthesis prompt. A post-processing filter then structurally removes any citation not in the whitelist. Verity cannot fabricate sourced evidence — if search fails, verdict is forced to Unverifiable with confidence ≤ 0.30.

### Stage 5 — Slack Delivery
Block Kit threaded reply with color-coded verdict attachment, tiered source badges, workspace memory section, and a Slack Canvas report link. Slack Lists logs every verdict for team-level moderation.

### Authority Tier System
A named, deliberate design decision — not a default pass-through:
- **Tier 1 (0.75–1.00):** .gov, .edu, .mil, PubMed, WHO, USDA, Nature, The Lancet, NEJM
- **Tier 2 (0.45–0.74):** Reuters, AP, BBC, The Guardian, Snopes, PolitiFact, FactCheck.org
- **Tier 3 (0.10–0.44):** General web, blogs, aggregators — included but weighted down

---

## Technologies Used (Hackathon Requirements)

**MCP Server Integration** — Core verification engine. Brave Search MCP server (Node/Express, SSE transport). Gemini calls it via a manual agentic tool loop. This is where live fact-finding happens.

**Real-Time Search (RTS) API** — Workspace memory. assistant.search.context searches the workspace's message history for prior discussions of the same claim. Adds institutional knowledge to every fact-check.

**Slack AI Capabilities** — Native delivery: Assistant SDK (AI thread with status updates + suggested prompts), Block Kit verdict formatting, Slack Canvas for persistent full reports, Slack Lists for claim directory.

All three technologies are used correctly and honestly — each does exactly one job.

---

## Challenges We Ran Into

**Instagram/TikTok ingestion** — We tested it on Day 1. Video download works, but Instagram exposes no transcript or caption API of any kind — confirmed against yt-dlp's own issue tracker. Getting spoken-word transcripts would require Whisper STT: ~10–30s latency, ~2GB model dependency, and a live-demo risk we weren't willing to take. Deliberately scoped out.

**Agentic loop event loop conflicts** — The Slack Bolt app uses threads; the MCP client is async. We built a persistent background event loop (mcp_client.py) with a dedicated thread and run_coroutine_threadsafe to bridge sync and async cleanly.

**Hallucinated citations** — Early versions of the synthesis prompt let Gemini invent plausible-looking URLs. We fixed this structurally: every URL retrieved by Brave Search goes into a numbered whitelist in the synthesis prompt, and a post-processing filter enforces it structurally.

**Web-evidence dependency** — Verity gathers all web evidence via a Brave Search MCP server over SSE. If that server is unreachable, it returns an honest "Unverifiable" verdict (confidence capped at 0.30) with no fabricated sources rather than guessing from parametric knowledge. This is the intended safety design, not a failure mode: a cold sandbox without the MCP server running will produce Unverifiable results by design.

---

## Accomplishments We're Proud Of

- **Anti-hallucination architecture** — Two-layer protection (whitelist in prompt + structural post-processing filter) means Verity's citations are provably grounded in real search results
- **Source authority as a named design decision** — The score_authority() function is explicit, inspectable, and testable — not buried middleware
- **Comparative claim handling** — Comparative claims are recognized and handled as multi-entity comparisons rather than single facts, so the agent reasons about rankings correctly
- **Full test suite** — All 4 pipeline modules have pytest tests with fixed inputs/outputs
- **Graceful degradation** — Every failure path produces a clean, honest UX — never a confident verdict from ungrounded knowledge

---

## What's Next for Verity

- Twitter/X post ingestion
- Multi-claim documents — long articles with many claims
- Team notifications — alert teammates when a claim has already been debunked
- Workspace-level claim history dashboard
- Fine-tuned claim extraction for edge cases

---

## Track

**Slack Agent for Good** — addressing misinformation as a public health problem.
Focus areas: public health, education, media literacy.
