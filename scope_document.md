# Project Scope Document

**Working name:** Verity
**Event:** Slack Agent Builder Hackathon (Devpost)
**Track:** Slack Agent for Good
**Team size:** 4
**Priority:** Win the competition. Every scope decision below is made against that criterion first.

---

## 1. Problem Statement

Misinformation now spreads fastest through short-form video and casual social content (Reels, TikTok, YouTube Shorts, tweets) — formats with no built-in way to check a claim's accuracy. Today, verifying a claim from a video means manually transcribing it, then separately prompting an LLM, then separately judging whether the sources it used are trustworthy. That friction means most people never check at all — they just believe it or scroll past.

**Concrete trigger case:** a user sees an Instagram Reel claiming a specific food has more protein than any other food, including chicken and eggs. There is no fast way to verify this in the moment.

## 2. Solution Overview

Verity is a Slack agent that takes a single pasted link (or plain text claim) and returns a sourced, source-quality-weighted verdict: **True / False / Misleading / Unverifiable**, with citations, posted back in-thread.

The core product bet is UX, not novelty of the AI itself: **one action (paste a link) → one clear, checkable answer.** The pipeline behind it (ingestion → transcription → claim extraction → verification → source-ranked answer) is what gets pitched as extensible to "any misinformation vector," but the MVP only has to prove the concept end-to-end on a narrow, reliable slice.

## 3. Target User

General audience — anyone in any Slack workspace who wants to fact-check something they saw before sharing or believing it. Framed in the pitch as: "the fact-check button the internet doesn't have."

## 4. MVP Scope (must work live, no exceptions)

This is the part that gets demoed and must not fail in the judges' sandbox. Kept deliberately narrow:

| Input type | Included in MVP | Why |
|---|---|---|
| YouTube video link | Yes | Reliable public transcript/caption access |
| Plain article / news link | Yes | Reliable text extraction, no scraping fragility |
| Plain pasted text/claim (no link) | Yes | Zero ingestion risk, fastest to build, good fallback demo path |
| Twitter/X post link | Stretch — build if time allows | Moderate reliability |
| Instagram Reel link | Stretch, demo-only if working | Highest risk: no public API, scraping-dependent, can break without warning |
| TikTok link | Out of scope for MVP | Same risk profile as IG, not worth doubling the risk surface |

**Rule for the team:** the Instagram Reel path gets attempted first, on day one, in isolation, before any agent logic is built around it. If it isn't reliably working by an internally agreed checkpoint, it is demoted to "shown as a bonus if it happens to work" and the actual demo script leads with YouTube/article/text instead. The pitch narrative ("this scales to any content type, including the messiest one") stays intact either way — Instagram is the stretch example, not the foundation.

## 5. Core Pipeline (architecture, all paths converge here)

1. **Ingestion** — detect input type (link vs plain text); route to the right extractor (video transcript API, article text extraction, or raw text passthrough).
2. **Claim extraction** — identify the specific, checkable claim(s) in the content. Must correctly identify claim *type* (e.g., comparative/superlative claim like "more protein than X and Y" is different from a single factual claim) — this is a deliberate build step, not automatic.
3. **Verification** — query for evidence using the Real-Time Search API and/or MCP-connected authoritative sources (e.g., government/health data, peer-reviewed sources, primary sources) rather than raw top-of-search-results content. Source-quality ranking is a named design decision, not an afterthought — this is a talking point for judges.
4. **Verdict synthesis** — produce a verdict (True / False / Misleading / Unverifiable) with confidence framing and cited sources, not just a flat yes/no.
5. **Slack delivery** — posted as a threaded reply, not a channel-flooding message. Uses Slack AI capabilities for formatting/summarization of the final response.

## 6. Enabling Technology Usage (per hackathon requirements — corrected)

**Important correction:** RTS is Slack's in-workspace search API (permission-aware access to a workspace's own conversations/files/threads) — it is not a general web search API. Verification against the outside world cannot run through RTS. Technology mapping, corrected:

- **MCP server integration (primary/core)** — connects Verity to external verification sources: a web-search MCP server (e.g. Brave Search, Exa) and/or a custom MCP server wrapping authoritative data sources. This is the actual verification engine and the main technical differentiation story for judges.
- **Real-Time Search (RTS) API (secondary/bonus)** — used honestly for what it's actually for: checking whether a claim has already been discussed in the current Slack workspace before running a fresh external verification. Adds a "workspace memory" feature; not the verification mechanism itself.
- **Slack AI capabilities** — response formatting and in-thread delivery of the verdict.

One technology per clear job, rather than stretching RTS to do something it doesn't do — this is a stronger, more honest pitch than the original draft.

## 7. Explicitly Out of Scope for MVP

- TikTok ingestion
- Multi-claim documents (long articles with many claims) — MVP handles single dominant claim
- User accounts / history / saved verdicts
- Any platform requiring login-walled scraping

These are listed in the pitch as "roadmap," not built for the demo.

## 8. Risks (ranked by how much they can sink the submission)

1. **Instagram/video scraping fragility** — highest risk, addressed by scoping order in Section 4 (build/test first, demote if unreliable).
2. **Weak source verification** — if verification just summarizes top search hits, it can re-launder existing misinformation instead of catching it. Mitigated by source-quality ranking (Section 5, step 3).
3. **Misidentified claim type** — verifying the wrong question (e.g., single-fact check when the real claim is comparative) gives a technically-answered-but-wrong verdict. Mitigated by dedicated claim-extraction step.
4. **Live demo failure** — mitigated by having a guaranteed-reliable fallback path (plain text / YouTube / article) that does not depend on the riskiest ingestion method.

## 9. Success Criteria for the Submission

- End-to-end working demo on at least 2 of the 3 MVP input types, live, not pre-recorded fallback.
- Clean architecture diagram showing the 5-stage pipeline and where RTS/MCP/Slack AI plug in.
- 3-minute demo video: opens with the real protein-claim scenario, shows the paste-link action, shows the verdict with sources, closes with the "extensible to any content type" pitch.
- Submission includes sandbox access shared with the required judge emails.

## 10. Open Items for Next Working Session

- Finalize which MCP-connected data sources to use for verification (domain-specific — depends on which example claims get used in the demo).
- Confirm exact Slack UX: slash command vs. paste-and-auto-detect vs. mention-the-bot.
- Assign the 4 team roles: (a) ingestion/claim extraction, (b) verification/RTS+MCP integration, (c) Slack app shell + UX, (d) architecture diagram + demo video + writeup (starts early, not last-minute).
