from __future__ import annotations

import dataclasses
import subprocess
import sys
import textwrap
from typing import ClassVar, Tuple

import msgspec.msgpack
import numpy as np
import pytest

from leika import _messages
from leika.infra import _messages as infra_messages


@dataclasses.dataclass
class _DirectShapeMessage(infra_messages.Message):
    count: int
    pair: Tuple[int, int]

    def redundancy_key(self) -> str:
        return "direct-shape"


@dataclasses.dataclass
class _NumericUnionMessage(infra_messages.Message):
    value: int | float

    def redundancy_key(self) -> str:
        return "numeric-union"


@dataclasses.dataclass
class _ArrayMessage(infra_messages.Message):
    values: np.ndarray

    def redundancy_key(self) -> str:
        return "array"


def test_late_public_message_subclass_invalidates_deserialization_lookup() -> None:
    class _DynamicRoot(infra_messages.Message):
        pass

    @dataclasses.dataclass
    class DynamicMessage(_DynamicRoot):
        value: str

        def redundancy_key(self) -> str:
            return "dynamic"

    # Prime the mapping, then define a second type. The latter must be visible
    # without callers knowing about or clearing an implementation cache.
    _DynamicRoot._subclass_from_type_string()

    @dataclasses.dataclass
    class LaterDynamicMessage(_DynamicRoot):
        value: str

        def redundancy_key(self) -> str:
            return "later-dynamic"

    payload = msgspec.msgpack.encode({"type": "LaterDynamicMessage", "value": "available"})
    decoded = _DynamicRoot.deserialize(payload)
    assert isinstance(decoded, LaterDynamicMessage)
    assert decoded.value == "available"


def test_duplicate_public_message_type_names_are_rejected_deterministically() -> None:
    # Class objects remain in ``__subclasses__()`` after creation, so isolate
    # this intentionally invalid graph from the rest of the test process.
    script = textwrap.dedent(
        """
        import dataclasses
        from leika.infra import Message

        def make_first():
            @dataclasses.dataclass
            class DuplicateWireName(Message):
                value: str
                def redundancy_key(self):
                    return "first"
            return DuplicateWireName

        def make_second():
            @dataclasses.dataclass
            class DuplicateWireName(Message):
                other: str
                def redundancy_key(self):
                    return "second"
            return DuplicateWireName

        make_first()
        make_second()
        Message._subclass_from_type_string()
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "duplicate protocol message type name 'DuplicateWireName'" in completed.stderr


def test_non_coalescing_message_key_is_unique_but_stable() -> None:
    first = _messages.RunJavascriptMessage("first")
    second = _messages.RunJavascriptMessage("second")

    assert first.redundancy_key() == first.redundancy_key()
    assert first.redundancy_key() != second.redundancy_key()
    assert first.redundancy_key() == _messages.RunJavascriptMessage("first").redundancy_key()
    assert "_cached_redundancy_key" not in first.as_serializable_dict()


def _decode(mapping: object) -> _messages.Message:
    return _messages.Message.deserialize(msgspec.msgpack.encode(mapping))


def test_decoded_shape_preflight_bounds_nodes_containers_and_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import leika.infra._messages as infra_messages

    monkeypatch.setattr(infra_messages, "_DECODED_NODE_LIMIT", 4)
    with pytest.raises(ValueError, match="too many values"):
        _decode({"type": "GuiUpdateMessage", "uuid": "x", "updates": [None, None]})

    monkeypatch.setattr(infra_messages, "_DECODED_NODE_LIMIT", 100)
    monkeypatch.setattr(infra_messages, "_DECODED_CONTAINER_ITEMS_LIMIT", 2)
    with pytest.raises(ValueError, match="too many items"):
        _decode({"type": "GuiUpdateMessage", "uuid": "x", "updates": [1, 2, 3]})

    monkeypatch.setattr(infra_messages, "_DECODED_CONTAINER_ITEMS_LIMIT", 100)
    monkeypatch.setattr(infra_messages, "_DECODED_DEPTH_LIMIT", 2)
    with pytest.raises(ValueError, match="nested too deeply"):
        _decode({"type": "GuiUpdateMessage", "uuid": "x", "updates": [[[None]]]})


def test_decoded_shape_preflight_bounds_aggregate_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import leika.infra._messages as infra_messages

    monkeypatch.setattr(infra_messages, "_DECODED_PAYLOAD_BYTES_LIMIT", 8)
    with pytest.raises(ValueError, match="payload is too large"):
        _decode({"type": "GuiUpdateMessage", "uuid": "x", "updates": {"x": "12345678"}})


def test_strict_decoder_reconstructs_nested_dataclasses_and_tuples() -> None:
    decoded = _decode(
        {
            "type": "GuiCheckboxMessage",
            "uuid": "checkbox",
            "value": True,
            "container_uuid": "root",
            "props": {
                "order": 1,
                "label": None,
                "hint": "help",
                "visible": True,
                "disabled": False,
            },
        }
    )
    assert isinstance(decoded, _messages.GuiCheckboxMessage)
    assert decoded.props == _messages.GuiCheckboxProps(
        order=1.0,
        label=None,
        hint="help",
        visible=True,
        disabled=False,
    )


@pytest.mark.parametrize("bad_value", [True, "1", 1.0, None])
def test_integer_fields_require_exact_int(bad_value: object) -> None:
    with pytest.raises(TypeError):
        _decode(
            {
                "type": "FileTransferStartUpload",
                "source_component_uuid": "upload",
                "transfer_uuid": "transfer",
                "filename": "safe.bin",
                "mime_type": "application/octet-stream",
                "part_count": bad_value,
                "size_bytes": 0,
            }
        )


@pytest.mark.parametrize("bad_value", [True, "0", 0.0, None])
def test_file_part_index_requires_exact_int(bad_value: object) -> None:
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
    ("field", "bad_value"),
    [
        ("uuid", 1),
        ("value", "false"),
        ("container_uuid", b"root"),
    ],
)
def test_message_scalars_are_strict(field: str, bad_value: object) -> None:
    mapping = {
        "type": "GuiCheckboxMessage",
        "uuid": "checkbox",
        "value": False,
        "container_uuid": "root",
        "props": {
            "order": 1.0,
            "label": "Label",
            "hint": None,
            "visible": True,
            "disabled": False,
        },
    }
    mapping[field] = bad_value
    with pytest.raises(TypeError):
        _decode(mapping)


@pytest.mark.parametrize(
    "mapping",
    [
        [],
        {"type": 4},
        {"type": "ClientPingMessage", "sent_ms": 1.0, "extra": "field"},
        {"type": "GuiUpdateMessage", "uuid": "gui", "updates": []},
        {
            "type": "GuiCheckboxMessage",
            "uuid": "gui",
            "value": True,
            "container_uuid": "root",
            "props": {
                "order": 1.0,
                "label": None,
                "hint": None,
                "visible": True,
                "disabled": False,
                "extra": True,
            },
        },
    ],
)
def test_malformed_envelopes_and_containers_are_rejected(mapping: object) -> None:
    with pytest.raises((TypeError, KeyError)):
        _decode(mapping)


@pytest.mark.parametrize(
    "mapping",
    [
        {"type": "ThemeConfigurationMessage", "control_layout": "bottom", "dark_mode": False},
        {"type": "ThemeConfigurationMessage", "control_layout": "left", "dark_mode": "yes"},
    ],
)
def test_literal_and_union_values_are_restricted(mapping: object) -> None:
    with pytest.raises(TypeError):
        _decode(mapping)


def test_tuple_shapes_and_elements_are_validated_recursively() -> None:
    with pytest.raises(TypeError):
        _decode(
            {
                "type": "GuiChecklistMessage",
                "uuid": "list",
                "value": [["one", "false"]],
                "container_uuid": "root",
                "props": {
                    "order": 1.0,
                    "label": None,
                    "hint": None,
                    "visible": True,
                    "disabled": False,
                },
            }
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_wire_float_is_rejected(value: float) -> None:
    payload = msgspec.msgpack.encode({"type": "ClientPingMessage", "sent_ms": value})
    with pytest.raises(ValueError, match="finite"):
        _messages.Message.deserialize(payload)


def test_object_and_structured_ndarrays_are_rejected_before_raw_storage_access() -> None:
    for values in (
        np.array([object()], dtype=object),
        np.array([(1, 2)], dtype=[("first", "i4"), ("second", "i4")]),
    ):
        message = _ArrayMessage(values)
        with pytest.raises(TypeError, match="numpy arrays"):
            message.validate_schema()
        with pytest.raises(TypeError, match="numpy arrays"):
            message.as_serializable_dict([])


@pytest.mark.parametrize(
    "dtype",
    ["|b1", "|u1", "|i1", "<u2", "<u4", "<i2", "<i4", "<f2", "<f4", "<f8"],
)
def test_browser_supported_ndarray_dtypes_are_serializable(dtype: str) -> None:
    message = _ArrayMessage(np.zeros(2, dtype=dtype))
    message.validate_schema()
    binary_buffers: list[memoryview] = []
    prepared = message.as_serializable_dict(binary_buffers)
    assert prepared["values"]["dtype"] == dtype
    assert len(binary_buffers) == 1


@pytest.mark.parametrize(
    "dtype", [">u2", ">i4", ">f8", "<u8", "<i8", "<c8", "S2", "U2", "M8[ns]", "m8[ns]"]
)
def test_unsupported_or_ambiguous_ndarray_dtypes_are_rejected(dtype: str) -> None:
    with pytest.raises(TypeError, match="not supported by the browser"):
        _ArrayMessage(np.zeros(2, dtype=dtype)).validate_schema()


@pytest.mark.parametrize("value", [-(1 << 53), 1 << 53])
def test_protocol_integers_must_be_javascript_safe(value: int) -> None:
    outbound = _messages.FileTransferStartUpload(
        source_component_uuid="component",
        transfer_uuid="transfer",
        filename="file.bin",
        mime_type="application/octet-stream",
        part_count=value,
        size_bytes=0,
    )
    with pytest.raises(ValueError, match="JavaScript-safe"):
        outbound.validate_schema()

    payload = msgspec.msgpack.encode(
        {
            "type": "FileTransferStartUpload",
            "source_component_uuid": "component",
            "transfer_uuid": "transfer",
            "filename": "file.bin",
            "mime_type": "application/octet-stream",
            "part_count": value,
            "size_bytes": 0,
        }
    )
    with pytest.raises(ValueError, match="JavaScript-safe"):
        _messages.Message.deserialize(payload)


@pytest.mark.parametrize("value", [-(1 << 53), 1 << 53])
def test_unsafe_integer_cannot_escape_through_float_union_arm(value: int) -> None:
    with pytest.raises(ValueError, match="JavaScript-safe"):
        _NumericUnionMessage(value).validate_schema()


def test_protocol_safe_integer_boundaries_are_accepted() -> None:
    for value in (-(1 << 53) + 1, (1 << 53) - 1):
        message = _messages.GuiUpdateMessage("component", {"value": value})
        message.validate_schema()


def test_outbound_dynamic_protocol_graph_rejects_cycles() -> None:
    cyclic: list[object] = []
    cyclic.append(cyclic)
    message = _messages.GuiUpdateMessage("component", {"value": cyclic})
    with pytest.raises(ValueError, match="reference cycle"):
        message.validate_schema()


def test_outbound_dynamic_protocol_graph_rejects_depth_and_fanout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(infra_messages, "_DECODED_DEPTH_LIMIT", 2)
    deep = [[[0]]]
    with pytest.raises(ValueError, match="nested too deeply"):
        _messages.GuiUpdateMessage("component", {"value": deep}).validate_schema()

    monkeypatch.setattr(infra_messages, "_DECODED_CONTAINER_ITEMS_LIMIT", 2)
    with pytest.raises(ValueError, match="too many items"):
        _messages.GuiUpdateMessage("component", {"value": [1, 2, 3]}).validate_schema()


def test_outbound_dynamic_protocol_graph_allows_shared_noncyclic_values() -> None:
    shared = [1, 2]
    _messages.GuiUpdateMessage("component", {"first": shared, "second": shared}).validate_schema()


def test_outbound_dynamic_mappings_require_string_keys() -> None:
    with pytest.raises(TypeError, match="mapping keys must be strings"):
        _messages.GuiUpdateMessage("component", {"value": {1: "not a record"}}).validate_schema()


def test_inbound_extension_and_nonstring_dynamic_mapping_keys_are_rejected() -> None:
    extension_payload = msgspec.msgpack.encode(
        {
            "type": "GuiUpdateMessage",
            "uuid": "component",
            "updates": {"value": msgspec.msgpack.Ext(1, b"x")},
        }
    )
    with pytest.raises(TypeError, match="unsupported decoded protocol value"):
        _messages.Message.deserialize(extension_payload)

    key_payload = msgspec.msgpack.encode(
        {
            "type": "GuiUpdateMessage",
            "uuid": "component",
            "updates": {"value": {1: "bad"}},
        }
    )
    with pytest.raises(TypeError, match="mapping keys must be strings"):
        _messages.Message.deserialize(key_payload)


def test_slots_defaults_and_init_false_fields_roundtrip_canonically() -> None:
    class _SlotsProtocolRoot(infra_messages.Message):
        pass

    @dataclasses.dataclass(slots=True)
    class SlotsDefaultMessage(_SlotsProtocolRoot):
        value: str
        defaulted: int = 7
        derived: str = dataclasses.field(default="derived", init=False)

        def redundancy_key(self) -> str:
            return "slots-default"

    message = SlotsDefaultMessage("payload")
    encoded = message.as_serializable_dict()
    assert encoded == {
        "value": "payload",
        "defaulted": 7,
        "derived": "derived",
        "type": "SlotsDefaultMessage",
    }
    decoded = _SlotsProtocolRoot.deserialize(msgspec.msgpack.encode(encoded))
    assert decoded == message


def test_unparameterized_tuple_annotation_is_rejected_bidirectionally() -> None:
    with pytest.raises(TypeError, match="Tuple annotation must have type arguments"):
        infra_messages._validate_for_serialization((), Tuple)
    with pytest.raises(TypeError, match="Tuple annotation must have type arguments"):
        infra_messages._prepare_for_deserialization([], Tuple)


def test_reserved_type_field_is_rejected_before_serialization() -> None:
    # Keep the intentionally invalid public class out of this process global
    # Message hierarchy; public subclasses are dynamically discoverable by
    # design and an invalid one must not poison unrelated later server tests.
    script = textwrap.dedent(
        """
        import dataclasses
        from leika.infra import Message

        class _ReservedProtocolRoot(Message):
            pass

        @dataclasses.dataclass
        class ReservedTypeMessage(_ReservedProtocolRoot):
            type: str
            def redundancy_key(self):
                return "reserved"

        errors = []
        for action in (
            lambda: ReservedTypeMessage("user-value").validate_schema(),
            _ReservedProtocolRoot._subclass_from_type_string,
        ):
            try:
                action()
            except TypeError as error:
                errors.append(str(error))
        assert len(errors) == 2
        assert all("reserved" in error and "type" in error for error in errors)
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_nested_optional_dataclass_roundtrips_init_false_fields_and_arrays() -> None:
    class _NestedProtocolRoot(infra_messages.Message):
        pass

    @dataclasses.dataclass(slots=True)
    class NestedRecord:
        label: str
        payload: bytes
        derived: str = dataclasses.field(default="initial", init=False)

    @dataclasses.dataclass
    class NestedOptionalMessage(_NestedProtocolRoot):
        nested: NestedRecord | None

        def redundancy_key(self) -> str:
            return "nested-optional"

    NestedOptionalMessage.__annotations__["nested"] = NestedRecord | None
    record = NestedRecord("value", b"payload")
    object.__setattr__(record, "derived", "wire-derived")
    message = NestedOptionalMessage(record)
    decoded = _NestedProtocolRoot.deserialize(
        msgspec.msgpack.encode(message.as_serializable_dict())
    )
    assert decoded == message

    @dataclasses.dataclass(slots=True)
    class ArrayRecord:
        values: np.ndarray
        derived: str = dataclasses.field(default="array-derived", init=False)

    @dataclasses.dataclass
    class OptionalArrayMessage(_NestedProtocolRoot):
        nested: ArrayRecord | None

        def redundancy_key(self) -> str:
            return "optional-array"

    OptionalArrayMessage.__annotations__["nested"] = ArrayRecord | None
    values = np.arange(4, dtype=np.float32)
    buffers: list[memoryview] = []
    prepared = OptionalArrayMessage(ArrayRecord(values)).as_serializable_dict(buffers)
    assert prepared["nested"] == {
        "values": {"__binary_index": 0, "dtype": "<f4"},
        "derived": "array-derived",
    }
    assert len(buffers) == 1
    assert bytes(buffers[0]) == values.tobytes()


def test_nested_dataclass_requires_the_exact_declared_wire_type() -> None:
    class _ExactNestedProtocolRoot(infra_messages.Message):
        pass

    @dataclasses.dataclass
    class BaseRecord:
        label: str

    @dataclasses.dataclass
    class ExtendedRecord(BaseRecord):
        extra: str

    @dataclasses.dataclass
    class ExactNestedMessage(_ExactNestedProtocolRoot):
        nested: BaseRecord

        def redundancy_key(self) -> str:
            return "exact-nested"

    ExactNestedMessage.__annotations__["nested"] = BaseRecord
    message = ExactNestedMessage(ExtendedRecord("base", "not-in-schema"))
    with pytest.raises(TypeError, match="BaseRecord"):
        message.validate_schema()
    with pytest.raises(TypeError, match="BaseRecord"):
        message.as_serializable_dict()


def test_inherited_class_variables_are_not_accepted_as_wire_fields() -> None:
    class _CanonicalFieldProtocolRoot(infra_messages.Message):
        inherited: ClassVar[str] = "internal"

    @dataclasses.dataclass
    class CanonicalFieldMessage(_CanonicalFieldProtocolRoot):
        value: str

        def redundancy_key(self) -> str:
            return "canonical-fields"

    payload = msgspec.msgpack.encode(
        {
            "type": "CanonicalFieldMessage",
            "value": "valid",
            "inherited": "forged",
        }
    )
    with pytest.raises(TypeError, match="unexpected message field"):
        _CanonicalFieldProtocolRoot.deserialize(payload)


def test_public_dataclass_base_and_child_are_both_wire_messages() -> None:
    class _InheritanceProtocolRoot(infra_messages.Message):
        pass

    @dataclasses.dataclass
    class BaseWireMessage(_InheritanceProtocolRoot):
        value: str

        def redundancy_key(self) -> str:
            return f"base-{self.value}"

    @dataclasses.dataclass
    class ChildWireMessage(BaseWireMessage):
        extra: int = 0

    discovered = _InheritanceProtocolRoot._subclass_from_type_string()
    assert discovered["BaseWireMessage"] is BaseWireMessage
    assert discovered["ChildWireMessage"] is ChildWireMessage
    assert _InheritanceProtocolRoot.deserialize(
        msgspec.msgpack.encode(BaseWireMessage("base").as_serializable_dict())
    ) == BaseWireMessage("base")
    assert _InheritanceProtocolRoot.deserialize(
        msgspec.msgpack.encode(ChildWireMessage("child", 7).as_serializable_dict())
    ) == ChildWireMessage("child", 7)


def test_valid_one_mi_utf16_text_round_trips_within_four_mib_payload_budget() -> None:
    # U+0800 costs three UTF-8 bytes but one UTF-16 code unit. This is the
    # worst ordinary GuiText round-trip under the browser's one-Mi-unit cap.
    value = "\u0800" * (1024 * 1024)
    message = _messages.GuiUpdateMessage("text", {"value": value})
    encoded = msgspec.msgpack.encode(message.as_serializable_dict())
    assert 2 * 1024 * 1024 < len(encoded) < 4 * 1024 * 1024
    decoded = _messages.Message.deserialize(encoded)
    assert isinstance(decoded, _messages.GuiUpdateMessage)
    assert decoded.updates == {"value": value}


def test_direct_serializable_dict_rejects_invalid_scalars_and_tuple_lengths() -> None:
    with pytest.raises(TypeError, match="expected.*int"):
        _DirectShapeMessage(1.5, (1, 2)).as_serializable_dict()  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="2 items"):
        _DirectShapeMessage(1, (1,)).as_serializable_dict()  # type: ignore[arg-type]
