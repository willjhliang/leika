from __future__ import annotations

from typing import Any

import msgspec.msgpack
import numpy as np
import pytest

from leika import _messages


def _decode(mapping: object) -> _messages.Message:
    return _messages.decode_message(msgspec.msgpack.encode(mapping))


def _checkbox(**overrides: Any) -> dict[str, Any]:
    return {
        "type": "GuiCheckboxMessage",
        "uuid": "checkbox",
        "value": False,
        "container_uuid": "root",
        "props": {"order": 1.0, "label": "Label", "hint": None, "visible": True, "disabled": False},
        **overrides,
    }


def test_registry_holds_every_public_message_and_no_private_base() -> None:
    assert _messages.MESSAGE_TYPES["GuiCheckboxMessage"] is _messages.GuiCheckboxMessage
    assert _messages.MESSAGE_TYPES["ViewportPaneMessage"] is _messages.ViewportPaneMessage
    assert not any(name.startswith("_") for name in _messages.MESSAGE_TYPES)


def test_encoded_message_round_trips_through_the_strict_decoder() -> None:
    message = _messages.GuiCheckboxMessage(
        uuid="checkbox",
        value=True,
        container_uuid="root",
        props=_messages.GuiCheckboxProps(
            order=1, label=None, hint="help", visible=True, disabled=False
        ),
    )
    decoded = _messages.decode_message(message.encode())
    assert decoded == message
    assert isinstance(decoded, _messages.GuiCheckboxMessage)
    assert type(decoded.props.order) is float


def test_encoding_carries_numpy_scalars_and_tuples_as_plain_values() -> None:
    message = _messages.GuiMultiSliderMessage(
        uuid="slider",
        value=(np.float32(0.5), 1),
        container_uuid="root",
        props=_messages.GuiMultiSliderProps(
            order=np.int64(2),
            label="Range",
            hint=None,
            visible=True,
            disabled=False,
            min=0.0,
            max=1.0,
            step=0.1,
            min_range=None,
            precision=1,
            fixed_endpoints=False,
            _marks=(_messages.GuiSliderMark(0.0, "low"),),
        ),
    )
    encoded = msgspec.msgpack.decode(message.encode())
    assert encoded["type"] == "GuiMultiSliderMessage"
    assert encoded["value"] == [0.5, 1]
    assert encoded["props"]["order"] == 2
    assert encoded["props"]["_marks"] == [{"value": 0.0, "label": "low"}]


@pytest.mark.parametrize(
    "message",
    [
        _messages.FileTransferPart(None, "transfer", 1.5, b""),  # type: ignore[arg-type]
        _messages.FileTransferPart(None, "transfer", True, b""),
        _messages.GuiVector2Message(
            "vector",
            (1.0,),
            "root",
            None,  # type: ignore[arg-type]
        ),
        _messages.ThemeConfigurationMessage("bottom", "light"),  # type: ignore[arg-type]
        _messages.GuiFolderMessage("folder", "root", _messages.GuiPopupProps(1.0, "x", True)),  # type: ignore[arg-type]
    ],
)
def test_outbound_fields_must_match_their_annotations(message: _messages.Message) -> None:
    with pytest.raises(TypeError):
        message.encode()


def test_dynamic_values_must_be_encodable() -> None:
    with pytest.raises(TypeError, match="unsupported"):
        _messages.GuiUpdateMessage("component", {"value": object()}).encode()
    assert _messages.validated_protocol_value_copy({"nested": [1, "two"]}) == {"nested": [1, "two"]}
    with pytest.raises(TypeError):
        _messages.validated_protocol_value_copy({"value": object()})


def test_non_lifecycle_messages_never_coalesce_by_default() -> None:
    assert _messages.RunJavascriptMessage("source").redundancy_key() is None
    assert _messages.ClientPingMessage(sent_ms=1.0).redundancy_key() is None
    assert _messages.GuiPreviewCancelMessage("button").redundancy_key() is None


def test_lifecycle_messages_derive_their_coalescing_keys() -> None:
    create = _messages.GuiTabMessage("tab", "group", "Label", None)
    remove = _messages.GuiRemoveMessage("tab")
    assert create.redundancy_key() == remove.redundancy_key()
    assert remove.purge_entities() == (("gui", "tab"),)
    assert create.purge_entities() == ()

    first = _messages.GuiUpdateMessage("gui", {"b": 1, "a": 2})
    same_props = _messages.GuiUpdateMessage("gui", {"a": 3, "b": 4})
    other_props = _messages.GuiUpdateMessage("gui", {"a": 5})
    assert first.redundancy_key() == same_props.redundancy_key() != other_props.redundancy_key()

    pane = _messages.ViewportPaneUpdateMessage("page", "pane", {"title": "x"})
    assert pane.lifecycle_entity() == ("viewport-content", ("page", "pane"))
    assert _messages.GuiFormSubmitMessage("form").redundancy_key() == (
        _messages.GuiFormSubmitMessage("form").redundancy_key()
    )


def test_singleton_state_messages_keep_only_the_latest() -> None:
    assert (
        _messages.ThemeConfigurationMessage("left", "dark").redundancy_key()
        == _messages.ThemeConfigurationMessage("right", "auto").redundancy_key()
    )
    assert (
        _messages.PageCatalogMessage(("a",)).redundancy_key()
        == _messages.PageCatalogMessage(("a", "b")).redundancy_key()
    )


def test_strict_decoder_reconstructs_nested_dataclasses_and_tuples() -> None:
    decoded = _decode(
        {
            "type": "GuiChecklistMessage",
            "uuid": "list",
            "value": [["one", True]],
            "container_uuid": "root",
            "props": {
                "order": 1,
                "label": None,
                "hint": None,
                "visible": True,
                "disabled": False,
                "frozen": False,
            },
        }
    )
    assert isinstance(decoded, _messages.GuiChecklistMessage)
    assert decoded.value == (("one", True),)
    assert decoded.props.order == 1.0


@pytest.mark.parametrize("bad_value", [True, "1", 1.0, None])
def test_integer_fields_require_exact_int(bad_value: object) -> None:
    with pytest.raises(TypeError):
        _decode(
            {
                "type": "FileTransferPart",
                "source_component_uuid": "upload",
                "transfer_uuid": "transfer",
                "part_index": bad_value,
                "content": b"",
            }
        )


@pytest.mark.parametrize(
    "mapping",
    [
        [],
        {"type": 4},
        {"type": "NoSuchMessage"},
        {"type": "ClientPingMessage", "sent_ms": 1.0, "extra": "field"},
        {"type": "ClientPingMessage"},
        {"type": "GuiUpdateMessage", "uuid": "gui", "updates": []},
        _checkbox(uuid=1),
        _checkbox(value="false"),
        _checkbox(container_uuid=b"root"),
        _checkbox(props={**_checkbox()["props"], "extra": True}),
        {"type": "ThemeConfigurationMessage", "control_layout": "bottom", "theme": "light"},
        {"type": "ThemeConfigurationMessage", "control_layout": "left", "theme": True},
        {"type": "ThemeConfigurationMessage", "control_layout": "left", "theme": None},
    ],
)
def test_malformed_messages_are_rejected(mapping: object) -> None:
    with pytest.raises(TypeError):
        _decode(mapping)


@pytest.mark.parametrize(
    ("value", "match"),
    [
        (float("nan"), "finite"),
        (float("inf"), "finite"),
        (1 << 53, "JavaScript-safe"),
        (-(1 << 53), "JavaScript-safe"),
    ],
)
def test_inbound_numbers_must_be_finite_and_javascript_safe(value: object, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _decode({"type": "ClientPingMessage", "sent_ms": value})


def test_inbound_extension_and_nonstring_dynamic_mapping_keys_are_rejected() -> None:
    with pytest.raises(TypeError, match="unsupported decoded protocol value"):
        _decode(
            {
                "type": "GuiUpdateMessage",
                "uuid": "c",
                "updates": {"v": msgspec.msgpack.Ext(1, b"x")},
            }
        )
    with pytest.raises(TypeError, match="mapping keys must be strings"):
        _decode({"type": "GuiUpdateMessage", "uuid": "c", "updates": {"v": {1: "bad"}}})


def test_decoded_shape_bounds_nodes_items_depth_and_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_messages, "_DECODED_NODE_LIMIT", 4)
    with pytest.raises(ValueError, match="too many values"):
        _decode({"type": "GuiUpdateMessage", "uuid": "x", "updates": [None, None]})

    monkeypatch.setattr(_messages, "_DECODED_NODE_LIMIT", 100)
    monkeypatch.setattr(_messages, "_DECODED_CONTAINER_ITEMS_LIMIT", 2)
    with pytest.raises(ValueError, match="too many items"):
        _decode({"type": "GuiUpdateMessage", "uuid": "x", "updates": [1, 2, 3]})

    monkeypatch.setattr(_messages, "_DECODED_CONTAINER_ITEMS_LIMIT", 100)
    monkeypatch.setattr(_messages, "_DECODED_DEPTH_LIMIT", 2)
    with pytest.raises(ValueError, match="nested too deeply"):
        _decode({"type": "GuiUpdateMessage", "uuid": "x", "updates": [[[None]]]})

    monkeypatch.setattr(_messages, "_DECODED_DEPTH_LIMIT", 64)
    monkeypatch.setattr(_messages, "_DECODED_PAYLOAD_BYTES_LIMIT", 8)
    with pytest.raises(ValueError, match="payload is too large"):
        _decode({"type": "GuiUpdateMessage", "uuid": "x", "updates": {"x": "12345678"}})


def test_valid_one_mi_utf16_text_round_trips_within_four_mib_payload_budget() -> None:
    # U+0800 costs three UTF-8 bytes but one UTF-16 code unit. This is the
    # worst ordinary GuiText round-trip under the browser's one-Mi-unit cap.
    value = "ࠀ" * (1024 * 1024)
    encoded = _messages.GuiUpdateMessage("text", {"value": value}).encode()
    assert 2 * 1024 * 1024 < len(encoded) < 4 * 1024 * 1024
    decoded = _messages.decode_message(encoded)
    assert isinstance(decoded, _messages.GuiUpdateMessage)
    assert decoded.updates == {"value": value}
