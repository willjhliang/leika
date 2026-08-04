from __future__ import annotations

from leika import _messages


def test_non_coalescing_message_key_is_unique_but_stable() -> None:
    first = _messages.RunJavascriptMessage("first")
    second = _messages.RunJavascriptMessage("second")

    assert first.redundancy_key() == first.redundancy_key()
    assert first.redundancy_key() != second.redundancy_key()
    assert "_cached_redundancy_key" not in first.as_serializable_dict()
