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


def test_story_count_mismatch_blocks(sample_digest: Digest) -> None:
    with pytest.raises(QualityGateError, match="expected 4"):
        check_quality(sample_digest, expected_story_count=4)
