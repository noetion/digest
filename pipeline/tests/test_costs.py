from __future__ import annotations

from types import SimpleNamespace

import pytest

from digest.costs import BudgetExceededError, CostTracker


def _usage(
    input_tokens: int = 0, cached: int = 0, output_tokens: int = 0, reasoning: int = 0
) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_tokens_details=SimpleNamespace(cached_tokens=cached),
        output_tokens_details=SimpleNamespace(reasoning_tokens=reasoning),
    )


def test_cost_computation_with_cached_discount() -> None:
    tracker = CostTracker(cap_usd=1.0)
    record = tracker.record("gpt-5-mini", _usage(input_tokens=1_000_000, cached=0))
    assert record.cost_usd == pytest.approx(0.25)

    tracker2 = CostTracker(cap_usd=1.0)
    record2 = tracker2.record("gpt-5-mini", _usage(input_tokens=1_000_000, cached=1_000_000))
    assert record2.cost_usd == pytest.approx(0.025)


def test_output_tokens_billed_at_output_rate() -> None:
    tracker = CostTracker(cap_usd=1.0)
    record = tracker.record("gpt-5-mini", _usage(output_tokens=500_000))
    assert record.cost_usd == pytest.approx(1.0)


def test_budget_guard_raises_once_cap_reached() -> None:
    tracker = CostTracker(cap_usd=0.10)
    tracker.check_budget()  # fine while nothing spent
    tracker.record("gpt-5-mini", _usage(output_tokens=100_000))  # $0.20 > cap
    with pytest.raises(BudgetExceededError):
        tracker.check_budget()


def test_missing_usage_details_handled() -> None:
    tracker = CostTracker(cap_usd=1.0)
    bare = SimpleNamespace(
        input_tokens=1000, output_tokens=100, input_tokens_details=None, output_tokens_details=None
    )
    record = tracker.record("gpt-5-nano", bare)
    assert record.cached_tokens == 0
    assert record.reasoning_tokens == 0


def test_summary_mentions_totals() -> None:
    tracker = CostTracker(cap_usd=1.0)
    tracker.record("gpt-5-nano", _usage(input_tokens=100, output_tokens=50))
    summary = tracker.summary()
    assert "1 LLM calls" in summary
    assert "input=100" in summary
