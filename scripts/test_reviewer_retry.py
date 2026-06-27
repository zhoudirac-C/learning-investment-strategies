"""Test reviewer retry counting and router force-pass logic."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qing_investment.agent.graph import edges, nodes


def test_reviewer_retry_limit():
    """Simulate three failed reviews and verify the router forces pass."""
    # Monkey-patch LLM call to return empty JSON so reviewer falls back to rules.
    original_safe_invoke = nodes._safe_llm_invoke
    nodes._safe_llm_invoke = lambda prompt: ""

    try:
        # styled_output contains a forbidden word -> fallback review fails.
        base_state = {
            "styled_output": "明天一定涨，建议无条件买入。",
            "claims": [],
            "_retry_count": 0,
        }

        state = base_state.copy()
        for i in range(4):
            result = nodes.reviewer(state)
            print(
                f"review attempt {i + 1}: passed={result['review_passed']} "
                f"retry_count_in={state.get('_retry_count', 0)} "
                f"retry_count_out={result['_retry_count']}"
            )

            route = edges.review_router(result)
            print(f"  -> review_router: {route}")

            if route == "pass":
                print(f"OK: graph exits after {i + 1} review attempt(s)")
                assert result["_retry_count"] >= 3, "expected retry_count >= 3 when forcing pass"
                return

            # Simulate style_writer consuming review_notes and producing same bad output.
            state = {
                **result,
                "styled_output": "明天一定涨，建议无条件买入。",
            }

        raise AssertionError("review_router should have forced pass by now")
    finally:
        nodes._safe_llm_invoke = original_safe_invoke


if __name__ == "__main__":
    test_reviewer_retry_limit()
    print("All reviewer retry tests passed.")
