"""Token accounting and the hard per-run budget guard."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# USD per 1M tokens. Update here if OpenAI reprices.
PRICES: dict[str, dict[str, float]] = {
    "gpt-5-nano": {"input": 0.05, "cached_input": 0.005, "output": 0.40},
    "gpt-5-mini": {"input": 0.25, "cached_input": 0.025, "output": 2.00},
}


class BudgetExceededError(RuntimeError):
    """Raised before a call that would blow past the daily cost cap."""


@dataclass
class CallRecord:
    model: str
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cost_usd: float


@dataclass
class CostTracker:
    cap_usd: float
    calls: list[CallRecord] = field(default_factory=list)

    @property
    def total_usd(self) -> float:
        return sum(c.cost_usd for c in self.calls)

    def record(self, model: str, usage: Any) -> CallRecord:
        """Record a completed call from the API response's usage object."""
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        input_details = getattr(usage, "input_tokens_details", None)
        cached = (getattr(input_details, "cached_tokens", 0) or 0) if input_details else 0
        output_details = getattr(usage, "output_tokens_details", None)
        reasoning = (
            (getattr(output_details, "reasoning_tokens", 0) or 0) if output_details else 0
        )

        prices = PRICES[model]
        uncached = input_tokens - cached
        cost = (
            uncached * prices["input"]
            + cached * prices["cached_input"]
            + output_tokens * prices["output"]
        ) / 1_000_000

        record = CallRecord(
            model=model,
            input_tokens=input_tokens,
            cached_tokens=cached,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning,
            cost_usd=cost,
        )
        self.calls.append(record)
        logger.info(
            "LLM call [%s]: in=%d (cached=%d) out=%d (reasoning=%d) cost=$%.5f",
            model,
            input_tokens,
            cached,
            output_tokens,
            reasoning,
            cost,
        )
        return record

    def check_budget(self) -> None:
        """Abort before the next call if the cap is already spent."""
        if self.total_usd >= self.cap_usd:
            raise BudgetExceededError(
                f"Run cost ${self.total_usd:.4f} has reached the cap ${self.cap_usd:.2f}; aborting."
            )

    def summary(self) -> str:
        total_in = sum(c.input_tokens for c in self.calls)
        total_cached = sum(c.cached_tokens for c in self.calls)
        total_out = sum(c.output_tokens for c in self.calls)
        total_reasoning = sum(c.reasoning_tokens for c in self.calls)
        return (
            f"{len(self.calls)} LLM calls | input={total_in} (cached={total_cached}) "
            f"output={total_out} (reasoning={total_reasoning}) | total=${self.total_usd:.4f}"
        )
