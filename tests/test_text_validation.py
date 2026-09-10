from __future__ import annotations

import json
import random

import pytest

import leika._plotly as plotly_impl
from leika._validation import (
    utf16_code_unit_length,
    utf16_code_unit_length_exceeds,
    validate_layout_id,
    validate_unicode_string,
)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "plain ASCII",
        "café 漢字",
        "a😀b𐀀",
        "\ud800x\udfff",
        "x" * 65_535 + "😀é" * 65_537,
    ],
)
def test_utf16_measurement_matches_wire_units_across_chunk_boundaries(text: str) -> None:
    expected = len(text.encode("utf-16-le", errors="surrogatepass")) // 2
    assert utf16_code_unit_length(text) == expected
    for limit in {0, len(text), 2 * len(text), expected - 1, expected, expected + 1}:
        assert utf16_code_unit_length_exceeds(text, limit) == (expected > limit)


def test_utf16_measurement_matches_mixed_unicode() -> None:
    random_source = random.Random(2026)
    alphabet = ["a", "é", "\u0000", "\ud800", "\uffff", "😀", "\U0010ffff"]
    for _ in range(100):
        text = "".join(random_source.choices(alphabet, k=random_source.randrange(100)))
        expected = sum(1 + (ord(character) > 0xFFFF) for character in text)
        assert utf16_code_unit_length(text) == expected
        for limit in [len(text), expected - 1, expected, 2 * len(text)]:
            assert utf16_code_unit_length_exceeds(text, limit) == (expected > limit)


@pytest.mark.parametrize("surrogate", ["\ud800", "\udbff", "\udc00", "\udfff"])
def test_unicode_validation_still_rejects_surrogates_at_any_position(surrogate: str) -> None:
    for text in [surrogate, "abc" + surrogate, "😀" + surrogate + "xyz"]:
        with pytest.raises(ValueError, match="surrogate"):
            validate_unicode_string(text, "text")
        with pytest.raises(ValueError, match="surrogate"):
            validate_layout_id(text, "id")
        with pytest.raises(ValueError, match="surrogate"):
            plotly_impl._plotly_string_json_upper_bound(text)


def _reference_json_bound(text: str) -> int:
    total = 2
    for character in text:
        codepoint = ord(character)
        if character in ('"', "\\"):
            total += 2
        elif codepoint < 0x20:
            total += 6
        elif codepoint > 0xFFFF:
            total += 12
        elif codepoint >= 0x7F:
            total += 6
        else:
            total += 1
    return total


@pytest.mark.parametrize(
    "text",
    [
        "",
        "base64/ABC+123==",
        "".join(chr(codepoint) for codepoint in range(128)),
        "ü漢字😀",
        "x" * 65_535 + '"\\\b\t\n\f\r😀' * 10_000,
    ],
)
def test_plotly_native_preflight_preserves_escaped_string_bound(text: str) -> None:
    bound = plotly_impl._plotly_string_json_upper_bound(text)
    assert bound == _reference_json_bound(text)
    assert bound >= len(json.dumps(text, ensure_ascii=True))


@pytest.mark.parametrize("text", ["x" * 20, "\n" * 4, "\x7f" * 4, "😀" * 2])
def test_plotly_preflight_checks_exact_limit(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    bound = _reference_json_bound(text)
    monkeypatch.setattr(plotly_impl, "_PLOTLY_JSON_MAX_UTF16_CODE_UNITS", bound)
    assert plotly_impl._plotly_string_json_upper_bound(text) == bound
    monkeypatch.setattr(plotly_impl, "_PLOTLY_JSON_MAX_UTF16_CODE_UNITS", bound - 1)
    with pytest.raises(ValueError, match="browser render limit"):
        plotly_impl._plotly_string_json_upper_bound(text)
