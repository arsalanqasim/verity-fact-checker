"""
Tests for src/pipeline/verdict.py

Per project convention (PROJECT_CONTEXT.md):
  Every pipeline module needs a unit test with a fixed input/output before
  it is considered done.

Planned test cases (to be implemented in Phase 4):
  - test_true_verdict: strong Tier-1 evidence confirming claim → verdict=True,
      confidence > 0.8
  - test_false_verdict: strong Tier-1 evidence contradicting claim → verdict=False
  - test_misleading_verdict: partially correct claim → verdict=Misleading
  - test_unverifiable_no_tier1: only Tier-3 sources available → verdict=Unverifiable
  - test_output_schema: all required JSON keys present and correctly typed
  - test_sources_list_non_empty: at least one cited source in output
"""

# import pytest
# from src.pipeline.verdict import synthesise_verdict


def test_placeholder():
    """Placeholder — replace with real tests when verdict.py is implemented."""
    assert True
