import dataclasses
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal, Optional, Tuple

import pytest

import leika
from leika._transport import _typescript
from leika._transport._typescript import _get_ts_type, generate_typescript_interfaces


@dataclasses.dataclass
class _Options:
    mode: Literal["one", "two", None]
    enabled: bool


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        (Tuple[str, int], "[string, number]"),
        (Tuple[float, ...], "(number)[]"),
        (list[bytes], "(Uint8Array<ArrayBuffer>)[]"),
        (dict[str, Any], "{[key: string]: any}"),
        (Optional[str], "(string | null)"),
        (bool | str, "(boolean | string)"),
        (Literal["quote'\"", 3], '"quote\'\\"" | 3'),
        (_Options, '{"mode": "one" | "two" | null, "enabled": boolean}'),
    ],
)
def test_annotations_map_to_typescript(annotation: object, expected: str) -> None:
    assert _get_ts_type(annotation) == expected


def test_unsupported_annotations_are_rejected() -> None:
    with pytest.raises(TypeError, match="Unsupported type annotation"):
        _get_ts_type(object)


def test_the_fingerprint_changes_with_the_package_version(monkeypatch: pytest.MonkeyPatch) -> None:
    before = _typescript.protocol_fingerprint()
    _typescript.protocol_fingerprint.cache_clear()
    monkeypatch.setattr(leika, "__version__", leika.__version__ + ".post1")
    try:
        assert _typescript.protocol_fingerprint() != before
    finally:
        _typescript.protocol_fingerprint.cache_clear()


def test_generated_protocol_compiles_and_types_real_messages(tmp_path: Path) -> None:
    client = Path(__file__).resolve().parents[1] / "src/leika/client"
    node = shutil.which("node")
    compiler = client / "node_modules/typescript/bin/tsc"
    if node is None or not compiler.is_file():
        pytest.skip("requires the frontend Node and TypeScript toolchain")

    checkbox = {
        "type": "GuiCheckboxMessage",
        "uuid": "checkbox",
        "value": True,
        "container_uuid": "root",
        "props": {"order": 1, "label": "Label", "hint": None, "visible": True, "disabled": False},
    }
    source = tmp_path / "protocol.ts"
    source.write_text(
        generate_typescript_interfaces()
        + f"\nconst checkbox: GuiCheckboxMessage = {json.dumps(checkbox)};\n"
        + "if (!isGuiComponentMessage(checkbox)) throw new Error('missing tag');\n"
        + "// @ts-expect-error A literal outside the schema does not type-check.\n"
        + "const theme: ThemeConfigurationMessage['theme'] = 'sepia';\n"
        + "void theme;\n",
        encoding="utf-8",
    )
    compiled = subprocess.run(
        [
            node,
            str(compiler),
            str(source),
            "--strict",
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
        [node, str(source.with_suffix(".js"))], capture_output=True, text=True, check=False
    )
    assert executed.returncode == 0, executed.stdout + executed.stderr
