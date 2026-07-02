from __future__ import annotations

from digest.models import Digest
from digest.synthesize import SYNTHESIS_SYSTEM_PROMPT, scrub_digest


def test_scrub_digest_removes_em_dashes(sample_digest: Digest) -> None:
    sample_digest.intro = "New silicon \u2014 and it ships this quarter."
    sample_digest.stories[0].why_it_matters = "Cheaper inference\u2014full stop."

    scrubbed = scrub_digest(sample_digest)

    assert scrubbed.intro == "New silicon, and it ships this quarter."
    assert scrubbed.stories[0].why_it_matters == "Cheaper inference-full stop."
    dumped = scrubbed.model_dump_json()
    assert "\u2014" not in dumped


def test_scrub_digest_leaves_clean_text_alone(sample_digest: Digest) -> None:
    before = sample_digest.model_dump_json()
    assert before == scrub_digest(sample_digest).model_dump_json()


def test_system_prompt_bans_em_dashes() -> None:
    assert "em dash" in SYNTHESIS_SYSTEM_PROMPT.lower()
