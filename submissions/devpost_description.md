# Verity — Devpost Submission Text Description
## Copy this into the Devpost project description form

---

## Inspiration

Every day, as I scroll through social media like Instagram, I see questionable claims and misinformation spreading rapidly. But there is no fast way to verify them in the moment. I tried sharing these reels and videos with ChatGPT and other LLMs, but they all said the same thing: they couldn't extract the exact captions or spoken details of the video. 

I thought: there should be an app or agent where I can just share a link, and it automatically goes out, searches through credible sources, and returns a detailed summary of the claim. When I saw the Slack Agent Builder Challenge on Devpost, it clicked — why not build this exact solution inside Slack? This way, I could implement the idea I had and bring instant verification directly into the workspace where teams share and discuss content.

**Verity is the fact-check button the internet doesn't have** — autonomously scanning shared links and delivering sourced answers right inside Slack where your team already shares and discusses content.

---

## What It Does

Verity is an autonomous, socially considerate Slack agent designed to curb the spread of misinformation in real-time. Instead of requiring users to manually check every claim, Verity actively works in the background to verify shared content and protect team communication.

### 1. Headline Feature: Proactive & Socially-Considerate Scanner (Autonomous)
Verity silently monitors workspace channels for shared links (YouTube videos or news articles). When a user posts a link:
- Verity automatically runs the verification pipeline in the background.
- If the source content is verified as **False** or **Misleading**, Verity sends an **ephemeral warning message** in the thread that is **visible only to the user who posted it**.
- This protects the channel from misinformation while **avoiding public embarrassment** — giving the poster a private opportunity to correct, delete, or address their message.

### 2. Manual Fact-Checking & Deep Dives (Secondary Trigger)
Users can also interact with Verity directly via the Slack Assistant tab or by mentioning `@Verity`:
- **Plain text claims**, **YouTube video links**, or **articles** can be pasted to request an on-demand verification.
- Verity replies with a complete, structured verdict in under 30 seconds.

### What you get back in every report:
- **Verdict with confidence score** (0–100%)
- **Concise summary of key evidence**
- **Sourced citations** with explicit authority tier badges (Tier 1 / Tier 2 / Tier 3)
- **Slack Canvas full report** that persists indefinitely for the team
- **Slack Lists claim directory entry** for workspace moderation
- **Workspace memory** — automatically surfacing any prior Slack discussions of the same claim

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

- **Proactive, socially-considerate autonomous scanning** — Verity listens to channel messages, automatically extracts claims, and warns users *ephemerally* (privately) if a claim is False or Misleading, preventing public embarrassment while safeguarding the channel
- **Anti-hallucination architecture** — Two-layer protection (whitelist in prompt + structural post-processing filter) means Verity's citations are provably grounded in real search results
- **Source authority as a named design decision** — The score_authority() function is explicit, inspectable, and testable — not buried middleware
- **Comparative claim handling** — Comparative claims are recognized and handled as multi-entity comparisons rather than single facts, so the agent reasons about rankings correctly
- **Full test suite** — All 6 pipeline modules/components have pytest tests with fixed inputs/outputs (66 total tests passing)
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
