from __future__ import annotations

from digest.extract import trim_text


def test_trims_at_paragraph_boundary() -> None:
    para = " ".join(["word"] * 100) + "."
    text = "\n\n".join([para] * 5)
    trimmed = trim_text(text, max_words=250)
    # 2 full paragraphs fit under 250 words; the third would overflow.
    assert trimmed.count("word") == 200


def test_first_paragraph_always_kept_even_if_over_cap() -> None:
    para = " ".join(["word"] * 50) + "."
    trimmed = trim_text(para, max_words=10)
    assert trimmed.count("word") == 50


def test_strips_trailing_boilerplate() -> None:
    text = (
        "This is a real paragraph with a proper ending sentence.\n\n"
        "Related articles\n\n"
        "Sign up for our newsletter"
    )
    trimmed = trim_text(text, max_words=1000)
    assert trimmed == "This is a real paragraph with a proper ending sentence."


def test_keeps_short_tail_with_sentence_punctuation() -> None:
    text = "A real paragraph ending properly.\n\nShort but real closing line."
    trimmed = trim_text(text, max_words=1000)
    assert "Short but real closing line." in trimmed


def test_collapses_excess_blank_lines() -> None:
    text = "First paragraph here.\n\n\n\n\nSecond paragraph here."
    trimmed = trim_text(text, max_words=1000)
    assert "\n\n\n" not in trimmed
