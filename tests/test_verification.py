"""
Tests for src/pipeline/verification.py

Per project convention (PROJECT_CONTEXT.md):
  Every pipeline module needs a unit test with a fixed input/output before
  it is considered done.

Planned test cases (to be implemented in Phase 3):
  - test_returns_weighted_results: mock MCP response → VerificationResult with
      tier-annotated sources
  - test_tier1_sources_ranked_first: results with mixed tiers → .gov / .edu
      items appear at head of list
  - test_rts_workspace_hit: mock RTS response with existing discussion →
      workspace_prior=True in result
  - test_mcp_error_raises: MCP server unreachable → raises VerificationError
      with informative message
"""

# import pytest
# from src.pipeline.verification import verify


def test_placeholder():
    """Placeholder — replace with real tests when verification.py is implemented."""
    assert True
