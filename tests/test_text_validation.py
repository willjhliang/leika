from __future__ import annotations

import pytest

from leika._validation import utf16_code_unit_length_exceeds, validate_unicode_string


@pytest.mark.parametrize("text", ["", "ASCII café 😀", "x" * 65_535 + "😀é" * 65_537])
def test_utf16_measurement_matches_wire_units_across_chunk_boundaries(text: str) -> None:
    expected = len(text.encode("utf-16-le")) // 2
    assert not utf16_code_unit_length_exceeds(text, expected)
    assert utf16_code_unit_length_exceeds(text, expected - 1)


@pytest.mark.parametrize("text", ["abc\ud800", "😀\udfffxyz"])
def test_unicode_validation_rejects_surrogates(text: str) -> None:
    with pytest.raises(ValueError, match="surrogate"):
        validate_unicode_string(text, "text")
