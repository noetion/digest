from __future__ import annotations

import logging

import pytest

from digest.models import Digest
from digest.quality import QualityGateError, check_quality


def test_good_digest_passes(sample_digest: Digest) -> None:
    check_quality(sample_digest)


def test_too_few_stories_blocks(sample_digest: Digest) -> None:
    sample_digest.stories = sample_digest.stories[:1]
    with pytest.raises(QualityGateError, match="only 1 stories"):
        check_quality(sample_digest)


def test_thin_digest_passes_when_expected(sample_digest: Digest) -> None:
    sample_digest.stories = sample_digest.stories[:2]
    check_quality(sample_digest, expected_story_count=2)


def test_thin_digest_still_blocks_one_story(sample_digest: Digest) -> None:
    sample_digest.stories = sample_digest.stories[:1]
    with pytest.raises(QualityGateError, match="only 1 stories"):
        check_quality(sample_digest, expected_story_count=1)


def test_empty_bullet_blocks(sample_digest: Digest) -> None:
    sample_digest.stories[0].why_it_matters = "Big."
    with pytest.raises(QualityGateError, match="why_it_matters too short"):
        check_quality(sample_digest)


def test_missing_sources_blocks(sample_digest: Digest) -> None:
    sample_digest.stories[1].source_urls = []
    with pytest.raises(QualityGateError, match="no source URLs"):
        check_quality(sample_digest)


def test_thin_narration_blocks(sample_digest: Digest) -> None:
    sample_digest.narration_script = "Good morning. That's all for today."
    with pytest.raises(QualityGateError, match="narration script too short"):
        check_quality(sample_digest)


def test_slop_vocabulary_warns_but_passes(
    sample_digest: Digest, caplog: pytest.LogCaptureFixture
) -> None:
    sample_digest.stories[0].why_it_matters = (
        "This groundbreaking release will revolutionize the seamless developer workflow."
    )
    with caplog.at_level(logging.WARNING):
        check_quality(sample_digest)
    assert "Slop vocabulary" in caplog.text
    assert "groundbreaking" in caplog.text


def test_outlook_filler_warns_but_passes(
    sample_digest: Digest, caplog: pytest.LogCaptureFixture
) -> None:
    sample_digest.stories[0].outlook = (
        "Watch for independent benchmark updates such as Artificial Analysis."
    )
    with caplog.at_level(logging.WARNING):
        check_quality(sample_digest)
    assert "Generic outlook filler" in caplog.text


def test_track_outlook_opener_warns(
    sample_digest: Digest, caplog: pytest.LogCaptureFixture
) -> None:
    sample_digest.stories[0].outlook = (
        "Track subscriber quota expirations through July 2026 for pricing changes."
    )
    with caplog.at_level(logging.WARNING):
        check_quality(sample_digest)
    assert "Generic outlook filler" in caplog.text


def test_follow_commits_outlook_warns(
    sample_digest: Digest, caplog: pytest.LogCaptureFixture
) -> None:
    sample_digest.stories[0].outlook = (
        "Follow commits on the GitHub repo for the next iPad memory fixes."
    )
    with caplog.at_level(logging.WARNING):
        check_quality(sample_digest)
    assert "Outlook reads like instructions" in caplog.text


def test_verification_to_watch_tail_warns(
    sample_digest: Digest, caplog: pytest.LogCaptureFixture
) -> None:
    sample_digest.stories[0].outlook = (
        "The OpenRouter window closes soon and Artificial Analysis remains "
        "the next external verification to watch."
    )
    with caplog.at_level(logging.WARNING):
        check_quality(sample_digest)
    assert "Passive outlook tail" in caplog.text


def test_fiscal_outlook_does_not_warn(
    sample_digest: Digest, caplog: pytest.LogCaptureFixture
) -> None:
    sample_digest.stories[0].outlook = (
        "Fiscal-year 2027 updates will show the remaining expected cuts and how "
        "Microsoft's Frontier Company investments translate into staffing changes."
    )
    with caplog.at_level(logging.WARNING):
        check_quality(sample_digest)
    assert "Generic outlook filler" not in caplog.text
    assert "Outlook reads like instructions" not in caplog.text


def test_outlook_instructions_warn_but_passes(
    sample_digest: Digest, caplog: pytest.LogCaptureFixture
) -> None:
    sample_digest.stories[0].outlook = (
        "Have marketing and legal review your next AI-assisted UX or ad before broad ad buys."
    )
    with caplog.at_level(logging.WARNING):
        check_quality(sample_digest)
    assert "Outlook reads like instructions" in caplog.text


def test_intro_count_mismatch_warns(
    sample_digest: Digest, caplog: pytest.LogCaptureFixture
) -> None:
    sample_digest.stories.append(
        sample_digest.stories[0].model_copy(
            update={
                "headline": "Vendor four ships a new inference stack for edge agents",
                "source_urls": ["https://example.com/4"],
            }
        )
    )
    sample_digest.stories.append(
        sample_digest.stories[0].model_copy(
            update={
                "headline": "Vendor five publishes agent release gates for production ML",
                "source_urls": ["https://example.com/5"],
            }
        )
    )
    sample_digest.intro = (
        "Three platform moves today matter for engineers: models, agents, and cuts."
    )
    with caplog.at_level(logging.WARNING, logger="digest.quality"):
        check_quality(sample_digest)
    assert "Intro count mismatch" in caplog.text


def test_story_count_mismatch_blocks(sample_digest: Digest) -> None:
    with pytest.raises(QualityGateError, match="expected 4"):
        check_quality(sample_digest, expected_story_count=4)
