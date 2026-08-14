import dataclasses
import json
import subprocess
import sys
from typing import Any, Dict, List, Literal, Tuple, TypedDict

import numpy as np
import numpy.typing as npt
import pytest

from leika.infra import Message
from leika.infra._typescript_interface_gen import (
    _get_ts_type,
    generate_typescript_interfaces,
    protocol_fingerprint,
)


@pytest.mark.parametrize(
    ("annotation", "message"),
    [
        (List, "List annotation must have one type argument"),
        (Dict, "Dict annotation must have two type arguments"),
        (Tuple, "Tuple annotation must have type arguments"),
        (object, "Unsupported type annotation"),
    ],
)
def test_invalid_annotations_raise_explicit_errors(annotation: object, message: str) -> None:
    with pytest.raises(TypeError, match=message):
        _get_ts_type(annotation)  # type: ignore[arg-type]


def test_invalid_annotations_are_still_rejected_in_optimized_mode() -> None:
    source = """
from typing import Dict, List, Tuple
from leika.infra import Message
from leika.infra._typescript_interface_gen import _get_ts_type, protocol_fingerprint

for annotation in (List, Dict, Tuple, object):
    try:
        _get_ts_type(annotation)
    except TypeError:
        continue
    raise RuntimeError(f"accepted invalid annotation {annotation!r}")
"""
    subprocess.run([sys.executable, "-O", "-c", source], check=True)


def test_dynamic_message_subclass_invalidates_protocol_fingerprint() -> None:
    class _FingerprintRoot(Message):
        pass

    before = protocol_fingerprint(_FingerprintRoot)

    @dataclasses.dataclass
    class LateFingerprintMessage(_FingerprintRoot):
        value: str

        def redundancy_key(self) -> str:
            return "late-fingerprint"

    after = protocol_fingerprint(_FingerprintRoot)
    assert after != before
    assert "LateFingerprintMessage" in (
        __import__(
            "leika.infra._typescript_interface_gen",
            fromlist=["generate_typescript_interfaces"],
        ).generate_typescript_interfaces(_FingerprintRoot)
    )


def test_runtime_validator_is_generated_from_nested_protocol_annotations() -> None:
    @dataclasses.dataclass
    class NestedRuntimeValue:
        enabled: bool

    class _RuntimeRoot(Message):
        pass

    @dataclasses.dataclass
    class RuntimeValidationMessage(_RuntimeRoot):
        count: int
        ratio: float
        nested: NestedRuntimeValue
        choice: Literal["one", "two"]
        pair: tuple[str, int]
        values: dict[str, Any]
        samples: npt.NDArray[np.float32]

        def redundancy_key(self) -> str:
            return "runtime-validation"

    source = generate_typescript_interfaces(_RuntimeRoot)

    assert "export function validateMessage" in source
    assert 'Number.isSafeInteger(message["count"])' in source
    assert 'Number.isFinite(message["ratio"])' in source
    assert '"samples": Float32Array' in source
    assert "pending.push(..." not in source
    assert "Object.values(" not in source


def test_literal_rich_struct_validator_keeps_record_guards_and_grouping() -> None:
    @dataclasses.dataclass
    class LiteralRichValue:
        mode: Literal["one", "two", None]
        enabled: Literal[True, False]

    class _LiteralRoot(Message):
        pass

    @dataclasses.dataclass
    class LiteralRichMessage(_LiteralRoot):
        value: LiteralRichValue

        def redundancy_key(self) -> str:
            return "literal-rich"

    source = generate_typescript_interfaces(_LiteralRoot)
    validator = source.split("function isProtocolStruct0(value: unknown): boolean {", 1)[1].split(
        "\n}\n", 1
    )[0]
    assert "isProtocolRecord(value) &&" in validator
    assert "Object.keys(value).length === 2 &&" in validator
    assert 'Object.hasOwn(value, "mode") &&' in validator
    assert 'Object.hasOwn(value, "enabled") &&' in validator
    assert (
        '(value["mode"] === "one" || value["mode"] === "two" || value["mode"] === null)'
    ) in validator
    assert '(value["enabled"] === true || value["enabled"] === false)' in validator


def test_runtime_validator_bounds_and_rejects_dangerous_identity_keys() -> None:
    class _IdentityRoot(Message):
        pass

    @dataclasses.dataclass
    class IdentityMessage(_IdentityRoot):
        uuid: str
        pane_ids: list[str]

        def redundancy_key(self) -> str:
            return "identity"

    source = generate_typescript_interfaces(_IdentityRoot)
    assert "PROTOCOL_IDENTIFIER_MAX_CODE_UNITS = 1024" in source
    assert "value.length > 0" in source
    assert 'value !== "__proto__"' in source
    assert "D800" in source
    assert 'isProtocolIdentifier(message["uuid"])' in source
    assert 'message["pane_ids"].every(isProtocolIdentifier)' in source


def test_generator_rejects_duplicate_wire_type_names() -> None:
    class _DuplicateRoot(Message):
        pass

    @dataclasses.dataclass
    class RepeatedWireName(_DuplicateRoot):
        value: str

        def redundancy_key(self) -> str:
            return "first"

    first = RepeatedWireName

    @dataclasses.dataclass
    class RepeatedWireName(_DuplicateRoot):  # type: ignore[no-redef]
        value: int

        def redundancy_key(self) -> str:
            return "second"

    assert first is not RepeatedWireName
    with pytest.raises(RuntimeError, match="duplicate protocol message type name"):
        generate_typescript_interfaces(_DuplicateRoot)


def test_generator_rejects_numpy_dtypes_the_browser_cannot_decode() -> None:
    assert _get_ts_type(npt.NDArray[np.bool_]) == "Uint8Array<ArrayBuffer>"
    with pytest.raises(TypeError, match="Unsupported browser numpy dtype"):
        _get_ts_type(npt.NDArray[np.complex64])


def test_typescript_literals_and_mapping_keys_are_json_escaped() -> None:
    separator = "\u2028"
    literal = f"quote'\"\\{separator}"
    expected = json.dumps(literal, ensure_ascii=True)
    assert _get_ts_type(Literal[None, literal]) == f"null | {expected}"

    WeirdKeys = TypedDict("WeirdKeys", {literal: str})
    assert _get_ts_type(WeirdKeys) == "{" + expected + ": string}"


@pytest.mark.parametrize("literal", [object(), 1 << 60, float("inf"), float("nan")])
def test_generator_rejects_unsafe_or_unsupported_literals(literal: object) -> None:
    with pytest.raises(TypeError, match="literal"):
        _get_ts_type(Literal[literal])


def test_generator_rejects_unsafe_message_and_tag_identifiers() -> None:
    class _IdentifierRoot(Message):
        pass

    bad_message = dataclasses.make_dataclass(
        "bad-message",
        [("value", str)],
        bases=(_IdentifierRoot,),
        namespace={"redundancy_key": lambda self: "bad"},
    )
    assert bad_message.__name__ == "bad-message"
    with pytest.raises(TypeError, match="message name.*safe TypeScript identifier"):
        generate_typescript_interfaces(_IdentifierRoot)

    class _TagRoot(Message):
        pass

    @dataclasses.dataclass
    class SafeName(_TagRoot):
        _tags = ("bad-tag",)
        value: str

        def redundancy_key(self) -> str:
            return "tag"

    with pytest.raises(TypeError, match="tag name.*safe TypeScript identifier"):
        generate_typescript_interfaces(_TagRoot)


@pytest.mark.parametrize(
    "reserved",
    [
        "interface",
        "implements",
        "package",
        "private",
        "protected",
        "public",
        "static",
        "let",
        "type",
        "namespace",
    ],
)
def test_generator_rejects_typescript_reserved_message_names(reserved: str) -> None:
    class _ReservedNameRoot(Message):
        pass

    dataclasses.make_dataclass(
        reserved,
        [("value", str)],
        bases=(_ReservedNameRoot,),
        namespace={"redundancy_key": lambda self: "reserved-name"},
    )
    with pytest.raises(TypeError, match="safe TypeScript identifier"):
        generate_typescript_interfaces(_ReservedNameRoot)


def test_generator_uses_canonical_dataclass_field_order_for_inheritance() -> None:
    class _OrderRoot(Message):
        pass

    @dataclasses.dataclass
    class OrderedBase(_OrderRoot):
        base_value: int

        def redundancy_key(self) -> str:
            return "base"

    @dataclasses.dataclass
    class OrderedChild(OrderedBase):
        child_value: str

        def redundancy_key(self) -> str:
            return "child"

    source = generate_typescript_interfaces(_OrderRoot)
    child = source.split("export interface OrderedChild", 1)[1].split("}", 1)[0]
    assert child.index('"base_value"') < child.index('"child_value"')


def test_generator_rejects_a_reserved_wire_discriminant_field() -> None:
    class _ReservedRoot(Message):
        pass

    @dataclasses.dataclass
    class ReservedMessage(_ReservedRoot):
        type: str

        def redundancy_key(self) -> str:
            return "reserved"

    with pytest.raises(TypeError, match="reserved 'type' field"):
        generate_typescript_interfaces(_ReservedRoot)
