from __future__ import annotations

from datetime import date

from digest.models import Digest
from digest.publish import build_devto_payload, canonical_digest_url, crosspost_to_devto


def test_canonical_url_format() -> None:
    assert (
        canonical_digest_url("https://morningbuild.dev/", date(2026, 7, 2))
        == "https://morningbuild.dev/digest/2026-07-02/"
    )


def test_devto_payload(sample_digest: Digest) -> None:
    payload = build_devto_payload(sample_digest, date(2026, 7, 2), "https://morningbuild.dev")
    article = payload["article"]
    assert article["title"] == sample_digest.title
    assert article["published"] is True
    assert article["tags"] == ["ai", "news", "programming", "technology"]
    assert article["canonical_url"] == "https://morningbuild.dev/digest/2026-07-02/"
    assert "## Acme ships 3nm inference chip" in article["body_markdown"]
    assert "Originally published at" in article["body_markdown"]


def test_crosspost_skipped_without_api_key(sample_digest: Digest) -> None:
    result = crosspost_to_devto(sample_digest, date(2026, 7, 2), "https://x.dev", api_key="")
    assert result is None


def test_crosspost_failure_is_non_fatal(sample_digest: Digest, monkeypatch) -> None:
    def boom(payload, api_key):  # noqa: ANN001, ANN202
        raise RuntimeError("network down")

    monkeypatch.setattr("digest.publish._post", boom)
    result = crosspost_to_devto(sample_digest, date(2026, 7, 2), "https://x.dev", api_key="key")
    assert result is None


def test_triage_input_uses_preview_not_full_text() -> None:
    from digest.models import FeedEntry
    from digest.triage import build_score_input

    entry = FeedEntry(
        title="Big story",
        url="https://example.com/a",
        source="Test",
        topic="ai",
        full_text=" ".join(["word"] * 500),
    )
    text = build_score_input([entry], [0])
    # Preview is capped at 80 words; the full 500-word text must never be sent to triage.
    assert text.count("word") == 80
