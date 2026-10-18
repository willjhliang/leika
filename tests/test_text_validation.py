from __future__ import annotations

import json

import pytest

import leika._plotly as plotly_impl
from leika._validation import (
    utf16_code_unit_length,
    utf16_code_unit_length_exceeds,
    validate_unicode_string,
)


@pytest.mark.parametrize("text", ["", "ASCII café 😀", "x" * 65_535 + "😀é" * 65_537])
def test_utf16_measurement_matches_wire_units_across_chunk_boundaries(text: str) -> None:
    expected = len(text.encode("utf-16-le")) // 2
    assert utf16_code_unit_length(text) == expected
    assert not utf16_code_unit_length_exceeds(text, expected)
    assert utf16_code_unit_length_exceeds(text, expected - 1)


@pytest.mark.parametrize("text", ["abc\ud800", "😀\udfffxyz"])
def test_unicode_validation_rejects_surrogates(text: str) -> None:
    with pytest.raises(ValueError, match="surrogate"):
        validate_unicode_string(text, "text")


def test_plotly_preflight_bounds_the_actual_serialized_text() -> None:
    text = "".join(chr(codepoint) for codepoint in range(128)) + 'ü漢字😀"\\' * 20_000
    bound = plotly_impl._plotly_string_json_upper_bound(text)
    assert bound >= len(json.dumps(text, ensure_ascii=True))


def test_plotly_preflight_checks_the_serialized_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    text = 'ASCII ü漢字😀"\\'
    size = len(json.dumps(text, ensure_ascii=True))
    monkeypatch.setattr(plotly_impl, "_PLOTLY_JSON_MAX_UTF16_CODE_UNITS", size)
    assert plotly_impl._plotly_string_json_upper_bound(text) == size
    monkeypatch.setattr(plotly_impl, "_PLOTLY_JSON_MAX_UTF16_CODE_UNITS", size - 1)
    with pytest.raises(ValueError, match="browser render limit"):
        plotly_impl._plotly_string_json_upper_bound(text)
