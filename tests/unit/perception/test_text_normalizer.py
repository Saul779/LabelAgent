"""TextNormalizer 基本行为。"""

from __future__ import annotations

from label_agent.perception.text.normalizer import TextNormalizer


def test_normalize_strips_control_chars_and_hashes() -> None:
    normalizer = TextNormalizer(max_chars=100)
    result = normalizer.normalize("Hello\x00World\r\n  Next")
    assert "\x00" not in result.text
    assert result.content_hash.startswith("sha256:")
    assert result.truncated is False


def test_normalize_truncates() -> None:
    normalizer = TextNormalizer(max_chars=5)
    result = normalizer.normalize("abcdefghij")
    assert result.text == "abcde"
    assert result.truncated is True
