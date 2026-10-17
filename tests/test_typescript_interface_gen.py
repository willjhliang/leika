import dataclasses
import json
import shutil
import subprocess
import sys
from pathlib import Path
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


def test_generated_protocol_compiles_and_validates_messages(tmp_path: Path) -> None:
    client = Path(__file__).resolve().parents[1] / "src/leika/client"
    node = shutil.which("node") or str(client / ".nodeenv/bin/node")
    compiler = client / "node_modules/typescript/bin/tsc"
    if not Path(node).is_file() or not compiler.is_file():
        pytest.skip("requires the frontend Node and TypeScript toolchain")

    escaped_text = "quote'\"\\\u2028"
    WeirdKeys = TypedDict("WeirdKeys", {escaped_text: str})

    @dataclasses.dataclass
    class Options:
        mode: Literal["one", "two", None]
        enabled: Literal[True, False]

    class _Root(Message):
        pass

    @dataclasses.dataclass
    class Base(_Root):
        uuid: str

        def redundancy_key(self) -> str:
            return self.uuid

    @dataclasses.dataclass
    class Payload(Base):
        count: int
        ratio: float
        options: Options
        pair: tuple[str, int]
        values: dict[str, Any]
        pane_ids: list[str]
        samples: npt.NDArray[np.float32]
        escaped: Literal[escaped_text]
        keyed: WeirdKeys

    source = tmp_path / "protocol.ts"
    source.write_text(
        generate_typescript_interfaces(_Root)
        + "\nconst escaped = "
        + json.dumps(escaped_text)
        + ";\n"
        + r"""
const valid: Payload = {
  type: "Payload", uuid: "pane", count: 3, ratio: 0.5,
  options: {mode: "two", enabled: true}, pair: ["label", 2],
  values: {nested: [null, 1, "text"]}, samples: new Float32Array([1, 2]),
  escaped, keyed: {[escaped]: "value"}, pane_ids: ["pane"],
};
validateMessage(valid);
validateMessage({...valid, options: {mode: null, enabled: false}});
for (const invalid of [
  {...valid, count: 1.5}, {...valid, ratio: Infinity},
  {...valid, options: null}, {...valid, options: {mode: "unknown", enabled: true}},
  {...valid, options: {mode: "one", enabled: "yes"}},
  {...valid, pair: ["label"]}, {...valid, samples: new Uint8Array([1, 2])},
  {...valid, uuid: "__proto__"}, {...valid, uuid: "x".repeat(PROTOCOL_IDENTIFIER_MAX_CODE_UNITS + 1)},
  {...valid, uuid: "\ud800"}, {...valid, unexpected: true},
  {...valid, escaped: "wrong"}, {...valid, keyed: {[escaped]: 42}},
  {...valid, pane_ids: ["__proto__"]},
]) {
  let rejected = false;
  try { validateMessage(invalid); } catch { rejected = true; }
  if (!rejected) throw new Error(`accepted invalid message: ${JSON.stringify(invalid)}`);
}
""",
        encoding="utf-8",
    )
    compiled = subprocess.run(
        [
            node,
            str(compiler),
            str(source),
            "--strict",
            "--skipLibCheck",
            "--target",
            "ES2022",
            "--module",
            "commonjs",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    executed = subprocess.run(
        [node, str(source.with_suffix(".js"))],
        capture_output=True,
        text=True,
        check=False,
    )
    assert executed.returncode == 0, executed.stdout + executed.stderr
