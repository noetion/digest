from __future__ import annotations

import pytest

from digest.models import Digest, Story


@pytest.fixture
def sample_digest() -> Digest:
    return Digest(
        title="The Morning Build for July 2, 2026: Chips, Agents, and a Big Open Release",
        intro="A dense day: new silicon, a major open-weights drop, and agent tooling grows up.",
        meta_description=(
            "New silicon, a major open-weights release, and agent tooling milestones "
            "in today's 2-minute AI/tech brief."
        ),
        stories=[
            Story(
                headline="Acme ships 3nm inference chip claiming 2x perf-per-watt",
                what_happened=(
                    "Acme announced the A100X, a 3nm inference accelerator with 192GB HBM4."
                ),
                why_it_matters=(
                    "Cheaper inference changes deployment economics for high-volume LLM workloads."
                ),
                outlook=(
                    "Q4 volume availability and cloud partner pricing will show "
                    "whether the perf-per-watt claims hold at production scale."
                ),
                source_urls=["https://example.com/acme-chip", "https://other.com/acme"],
                topic_tag="chips",
            ),
            Story(
                headline="OpenLab releases 70B open-weights model under Apache 2.0",
                what_happened=(
                    "OpenLab published weights, training recipe, and evals for its 70B model."
                ),
                why_it_matters="Engineers get a commercially usable frontier-class base model.",
                outlook=(
                    "Community fine-tuned variants and independent eval reruns "
                    "over the next few weeks will test the base model claims."
                ),
                source_urls=["https://example.com/openlab"],
                topic_tag="ai",
            ),
            Story(
                headline="EU publishes final implementation timeline for AI Act audits",
                what_happened=(
                    "The EU released the enforcement schedule for AI Act conformity audits, "
                    "with the first deadlines for general-purpose models landing next March."
                ),
                why_it_matters=(
                    "Teams shipping models into the EU now have concrete compliance dates "
                    "to plan documentation and evaluation work against."
                ),
                outlook="Member-state regulators publish detailed audit guidance next quarter.",
                source_urls=["https://example.com/eu-ai-act"],
                topic_tag="policy",
            ),
        ],
        narration_script=(
            "Good morning, it's Thursday July second. Two stories worth your time today. "
            "First up, chips. Acme announced the A100X, a three nanometer inference "
            "accelerator carrying one hundred ninety two gigabytes of HBM4 memory. The "
            "company claims twice the performance per watt of its previous generation. "
            "That matters because inference cost dominates the economics of serving "
            "large language models in production, so a real efficiency jump of that "
            "size cuts the bill for high volume workloads. Volume availability is "
            "slated for the fourth quarter. Second, open models. OpenLab published "
            "full weights, the training recipe, and evaluation results for its "
            "seventy billion parameter model under Apache two point zero. Engineers "
            "get a commercially usable frontier class base model with no research "
            "only restrictions. Expect community fine tuned variants within weeks. "
            "That's the briefing. Back tomorrow morning."
        ),
    )
