"""
Tests for src/pipeline/claims.py

Per project convention (PROJECT_CONTEXT.md):
  Every pipeline module needs a unit test with a fixed input/output before
  it is considered done.

Planned test cases (to be implemented in Phase 2):
  - test_single_fact_claim: "The Eiffel Tower is 330 m tall." → type=SINGLE_FACT
  - test_comparative_claim: "Lentils have more protein than chicken and eggs."
      → type=COMPARATIVE, entities=[lentils, chicken, eggs]
  - test_superlative_claim: "X is the most Y in Z." → type=SUPERLATIVE
  - test_causal_claim: "Eating X causes Y." → type=CAUSAL
  - test_empty_input_raises: "" → ValueError
"""

# import pytest
# from src.pipeline.claims import extract_claims


def test_placeholder():
    """Placeholder — replace with real tests when claims.py is implemented."""
    assert True
