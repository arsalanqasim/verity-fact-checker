"""
Stage 3 & 4 — Autonomous Agentic Search & Synthesis Loop

Responsibility:
  Coordinates the autonomous fact-checking loop. Gives Gemini access to
  Brave Search MCP as a tool, allowing the agent to formulate queries,
  evaluate results, refine its strategy, and synthesize a structured verdict.
"""

from __future__ import annotations

import logging
import os
from typing import Literal
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src.pipeline.verification import verify_claim

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured Output Schema
# ---------------------------------------------------------------------------

class _SourceSchema(BaseModel):
    title: str = Field(description="The title of the source page or document.")
    url: str = Field(
        description=(
            "The URL of the source. "
            "MUST be copied verbatim from the 'URL:' field of one of the Evidence items "
            "returned by search_web_evidence. Do not construct, paraphrase, or invent URLs."
        )
    )
    tier: int = Field(description="The authority tier of the source: 1, 2, or 3.")


class _VerdictSchema(BaseModel):
    verdict: Literal["True", "False", "Misleading", "Unverifiable"] = Field(
        description="The final verdict for the claim. Must be exactly: True, False, Misleading, or Unverifiable."
    )
    confidence: float = Field(
        description="Confidence score for the verdict, between 0.0 and 1.0."
    )
    summary: str = Field(
        description="A concise, one-sentence explanation of the verdict, summarizing the key evidence."
    )
    sources: list[_SourceSchema] = Field(
        description="List of sources from the search results that were actually used to synthesize this verdict."
    )

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def search_web_evidence(query: str) -> str:
    """
    Search the web for evidence to verify a factual claim.
    
    Parameters:
        query: The search query to run on the web search engine.
        
    Returns:
        A formatted string of evidence snippets annotated with source authority scores and tiers.
    """
    logger.info(f"[Agent Tool Execution] Running Brave Search for: '{query}'")
    res = verify_claim(query, claim_type="single_fact")
    if not res.get("success"):
        return f"Search error: {res.get('error', 'unknown error')}"
        
    evidence = res.get("evidence", [])
    if not evidence:
        return f"No search results found for query: '{query}'."

    # Full, untruncated evidence dump at DEBUG level for provenance auditing.
    logger.debug(
        "[Agent Tool Evidence] Full evidence list for query '%s' (%d items):\n%s",
        query,
        len(evidence),
        "\n".join(
            f"  [{i}] Tier {e.get('authority_tier')} Score {e.get('authority_score'):.2f} "
            f"URL={e.get('source_url')} Title={e.get('title')}"
            for i, e in enumerate(evidence, 1)
        ),
    )
        
    formatted = []
    for idx, item in enumerate(evidence, start=1):
        formatted.append(
            f"Evidence [{idx}]:\n"
            f"  Title: {item.get('title')}\n"
            f"  URL: {item.get('source_url')}\n"
            f"  Tier: {item.get('authority_tier')}\n"
            f"  Score: {item.get('authority_score'):.2f}\n"
            f"  Snippet: {item.get('snippet')}\n"
        )
    return "\n".join(formatted)

# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert, autonomous fact-checking agent. Your goal is to evaluate if a target claim is True, False, Misleading, or Unverifiable.

You have access to the tool `search_web_evidence` to query the web.

Instructions:
1. Formulate a search plan. Decide what queries are needed to find authoritative evidence.
2. Call `search_web_evidence` with your query.
3. Review the returned evidence snippets. Note their authority tiers:
   - Tier 1 (.gov, .edu, journals, PubMed, USDA) is highly trusted.
   - Tier 2 (established news wires, reputable news outlets, specialized fact-checkers) is moderately trusted.
   - Tier 3 (blogs, general web, social media, forums) is low trust.
4. Autonomous Self-Correction: If a search query returns "No search results found" or only returns low-trust Tier 3 evidence, you MUST rewrite your query. Formulate a new query using alternative phrasings, synonyms, broader terms, or key nouns from the claim, and run search_web_evidence again. Do not give up after a single empty search.
5. Note: You do not need exhaustive research for well-established claims. Once you have 2–3 corroborating or contradicting sources from Tier 1 or Tier 2, or once further searches are returning duplicate/unhelpful results, stop calling tools and produce your final verdict.
6. Once you have gathered sufficient evidence, synthesize the final verdict:
   - True: The claim is fully supported by Tier-1 or Tier-2 evidence with no significant caveats.
   - False: The claim is directly contradicted by Tier-1 or Tier-2 evidence.
   - Misleading: The claim contains some truth but leaves out critical context, exaggerates, or misrepresents facts.
   - Unverifiable: There is not enough reliable Tier-1 or Tier-2 evidence to confirm or deny the claim, or the evidence is heavily contradictory/inconclusive.
7. Enforce "Unverifiable" if there is no Tier-1 or Tier-2 evidence available at all.
8. Populate the sources list with the actual titles and URLs of the pages you used from the search results, mapping them to their correct Tier (1, 2, or 3).

Your final output must conform to the required JSON schema.
"""

# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------

_MODEL = "gemini-3.1-flash-lite"

def run_agent(claim: str, strict: bool = True) -> dict:
    """
    Run the autonomous fact-checking agent on a claim.
    
    Parameters:
        claim: The factual claim statement.
        
    Returns:
        dict containing verdict, confidence, summary, sources, success, and error.
    """
    if not claim or not claim.strip():
        return {
            "verdict": "Unverifiable",
            "confidence": 0.0,
            "summary": "No claim provided.",
            "sources": [],
            "success": False,
            "error": "Claim string was empty."
        }

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return {
            "verdict": "Unverifiable",
            "confidence": 0.0,
            "summary": "Gemini API key is not configured.",
            "sources": [],
            "success": False,
            "error": "GEMINI_API_KEY is not set in the environment."
        }

    logger.info(f"Running autonomous fact-checking agent for claim: '{claim}'")

    prompt = (
        f"{_SYSTEM_PROMPT}\n\n"
        f"Claim to evaluate: {claim}\n"
    )

    try:
        import json
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        # Initialize conversation contents history starting with user prompt
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=prompt)]
            )
        ]

        # Config for tool-calling turns (does not enforce JSON schema to allow function calling)
        tool_config = types.GenerateContentConfig(
            tools=[search_web_evidence],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0,
        )

        max_iterations = 4
        seen_calls = set()
        searches_succeeded = False  # True once any search_web_evidence call returns real results
        # Accumulate every URL returned by any search tool call.
        # Used to (a) build the synthesis whitelist and (b) strip hallucinated citations.
        retrieved_urls: set[str] = set()

        for iteration in range(1, max_iterations + 1):
            logger.info(f"[Agentic Loop] Turn {iteration}/{max_iterations}...")
            response = client.models.generate_content(
                model=_MODEL,
                contents=contents,
                config=tool_config
            )

            # Record model content in history
            if response.candidates and response.candidates[0].content:
                contents.append(response.candidates[0].content)
            else:
                logger.warning("[Agentic Loop] Empty candidate content received from model.")
                break

            # Handle function calls if any
            if response.function_calls:
                tool_parts = []
                for function_call in response.function_calls:
                    func_name = function_call.name
                    func_args = function_call.args
                    
                    # Deduplication key (name + stringified args)
                    call_key = (func_name, json.dumps(func_args, sort_keys=True))
                    logger.info(f"[Agentic Loop] Model requested tool call: {func_name}({func_args})")
                    
                    if call_key in seen_calls:
                        logger.warning(f"[Agentic Loop] Duplicate tool call detected: {func_name}({func_args}). Short-circuiting.")
                        # Inject synthetic response directing model toward synthesis
                        result_str = (
                            "This exact query was already run and returned results. "
                            "Do not repeat queries. Synthesize your final verdict based on the existing evidence gathered so far."
                        )
                    else:
                        seen_calls.add(call_key)
                        if func_name == "search_web_evidence":
                            query = func_args.get("query", "")
                            result_str = search_web_evidence(query=query)
                            # Track whether any real evidence came back.
                            # Error strings start with "Search error:" or "No search results found".
                            if not (result_str.startswith("Search error:") or
                                    result_str.startswith("No search results found")):
                                searches_succeeded = True
                                # Parse URLs out of the formatted evidence string so we can
                                # build the whitelist for the synthesis prompt.
                                import re as _re
                                for _url in _re.findall(r"^  URL: (.+)$", result_str, _re.MULTILINE):
                                    retrieved_urls.add(_url.strip())
                        else:
                            result_str = f"Error: unknown tool '{func_name}'"

                    logger.info(
                        "[Agentic Loop] Tool response for '%s' (%d chars)",
                        func_name, len(result_str)
                    )
                    tool_parts.append(
                        types.Part.from_function_response(
                            name=func_name,
                            response={"result": result_str}
                        )
                    )
                
                # Record tool responses in history
                contents.append(
                    types.Content(
                        role="tool",
                        parts=tool_parts
                    )
                )
            else:
                # No function calls, model returned final text response
                logger.info("[Agentic Loop] Model did not request any tools. Finalizing response.")
                break

        # Synthesis/Fallback Turn: Force final output to match response_schema.
        # The synthesis prompt depends on whether any real search results were obtained.
        # If searches_succeeded is False, instruct the model to issue an Unverifiable
        # verdict rather than fabricating sourced evidence from general knowledge.
        logger.info("[Agentic Loop] Running structured synthesis turn (tools disabled)...")

        if searches_succeeded:
            # Build an explicit numbered whitelist of every URL retrieved.
            # The model is instructed to select only from this list — it cannot
            # construct or invent URLs.
            if retrieved_urls:
                whitelist_lines = "\n".join(
                    f"  {i}. {url}" for i, url in enumerate(sorted(retrieved_urls), 1)
                )
                url_constraint = (
                    f"\n\nPERMITTED SOURCE URLs — you may ONLY cite URLs from this exact list. "
                    f"Do not alter, combine, or invent any URL. "
                    f"Do not add sources from your general knowledge.\n{whitelist_lines}"
                )
            else:
                url_constraint = ""

            synthesis_user_prompt = (
                "Give your best verdict now based on the search evidence gathered above. "
                "Do not call any more tools. "
                "You MUST respond with a JSON conforming to the required verdict schema."
            )
            if strict:
                synthesis_user_prompt += "\nREMEMBER: You MUST enforce 'Unverifiable' if there is no Tier-1 or Tier-2 evidence available."
            else:
                synthesis_user_prompt += "\nNOTE: Since strict verification is disabled, you may use Tier-3 evidence (general web, blogs, forums) to synthesize a True/False/Misleading verdict if higher-tier sources are unavailable."
            synthesis_user_prompt += url_constraint
        else:
            synthesis_user_prompt = (
                "All web search attempts failed — no live evidence was retrieved. "
                "You MUST set verdict to 'Unverifiable', confidence to 0.2 or lower, "
                "and sources to an empty list. "
                "In the summary field, state plainly that live web search was unavailable "
                "and that no independent verification could be performed. "
                "Do NOT fabricate source URLs or cite general knowledge as sourced evidence. "
                "You MUST respond with a JSON conforming to the required verdict schema."
            )

        contents.append(
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=synthesis_user_prompt)
                ]
            )
        )

        # Fresh GenerateContentConfig WITHOUT tools key to prevent API rejection of JSON response schema
        synthesis_config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_VerdictSchema,
            temperature=0,
        )

        response = client.models.generate_content(
            model=_MODEL,
            contents=contents,
            config=synthesis_config
        )
        raw_json = response.text

        if not raw_json:
            return {
                "verdict": "Unverifiable",
                "confidence": 0.0,
                "summary": "Empty response from agent model during synthesis.",
                "sources": [],
                "success": False,
                "error": "Gemini returned an empty response during synthesis."
            }

        parsed = _VerdictSchema.model_validate_json(raw_json)

        # ── Post-processing provenance filter ────────────────────────────────
        # Remove any source whose URL was not in the retrieved evidence.
        # This is defense-in-depth: the whitelist in the synthesis prompt should
        # prevent hallucinated URLs, but we enforce it structurally here as well.
        if retrieved_urls:
            clean_sources = [
                s for s in parsed.sources
                if s.url.strip() in retrieved_urls
            ]
            hallucinated_count = len(parsed.sources) - len(clean_sources)
            if hallucinated_count:
                logger.warning(
                    "[Agent] Stripped %d hallucinated citation(s) not in retrieved evidence: %s",
                    hallucinated_count,
                    [s.url for s in parsed.sources if s.url.strip() not in retrieved_urls],
                )
        else:
            clean_sources = parsed.sources

        # Mathematical Confidence Calibration:
        # Enforce bounds to prevent model from hallucinating high confidence:
        # - If there is no Tier 1 or Tier 2 evidence cited, cap confidence at 0.40.
        # - If the verdict is Unverifiable, cap confidence at 0.30.
        calibrated_confidence = parsed.confidence
        has_high_tier_source = any(s.tier in (1, 2) for s in clean_sources)
        if not has_high_tier_source:
            calibrated_confidence = min(calibrated_confidence, 0.40)
        if parsed.verdict == "Unverifiable":
            calibrated_confidence = min(calibrated_confidence, 0.30)
            
        logger.info(
            "[Agent Calibration] Raw confidence: %.2f -> Calibrated: %.2f (Verdict: %s, High-Tier Source: %s)",
            parsed.confidence,
            calibrated_confidence,
            parsed.verdict,
            has_high_tier_source
        )

        return {
            "verdict": parsed.verdict,
            "confidence": calibrated_confidence,
            "summary": parsed.summary,
            "sources": [
                {"title": s.title, "url": s.url, "tier": s.tier}
                for s in clean_sources
            ],
            "search_succeeded": searches_succeeded,
            "success": True,
            "error": None
        }

    except Exception as exc:
        logger.error(f"Agent execution failed: {exc}", exc_info=True)
        return {
            "verdict": "Unverifiable",
            "confidence": 0.0,
            "summary": "Failed to synthesize verdict due to an error.",
            "sources": [],
            "success": False,
            "error": f"Agent API error: {exc}"
        }
