from __future__ import annotations

import base64
import csv
import hashlib
import io
import stat
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts import _artifact_metadata, check_sdist, check_wheel


def _record_row(name: str, payload: bytes) -> list[str]:
    digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()
    return [name, f"sha256={digest}", str(len(payload))]


def _metadata(
    module: object,
    version: str,
    license_headers: str,
    *,
    duplicate_name: bool = False,
    omit_first_requirement: bool = False,
) -> bytes:
    project = _artifact_metadata.project_metadata()
    requirements = _artifact_metadata.expected_requires_dist(project)
    if omit_first_requirement:
        requirements = requirements[1:]
    fields = [
        "Metadata-Version: 2.4",
        "Name: leika",
        *(["Name: leika"] if duplicate_name else []),
        f"Version: {version}",
        f"Requires-Python: {project['requires-python']}",
        f"License-Expression: {module.EXPECTED_LICENSE}",
        *(f"Project-URL: {name}, {url}" for name, url in project["urls"].items()),
        *(f"Classifier: {value}" for value in project["classifiers"]),
        *(f"Requires-Dist: {value}" for value in requirements),
        *(f"Provides-Extra: {value}" for value in _artifact_metadata.expected_extras(project)),
        license_headers.rstrip("\n"),
        "",
    ]
    return "\n".join(fields).encode()


def _minimal_wheel(
    path: Path,
    *,
    bad_hash: bool = False,
    missing_core_file: bool = False,
    missing_license_metadata: bool = False,
    duplicate_name: bool = False,
    omit_first_requirement: bool = False,
    version: str = "0.4.0",
) -> None:
    dist_info = f"leika-{version}.dist-info"
    metadata_name = f"{dist_info}/METADATA"
    record_name = f"{dist_info}/RECORD"
    license_files = sorted(check_wheel._expected_license_files())
    license_headers = (
        ""
        if missing_license_metadata
        else "".join(f"License-File: {name}\n" for name in license_files)
    )
    metadata = _metadata(
        check_wheel,
        version,
        license_headers,
        duplicate_name=duplicate_name,
        omit_first_requirement=omit_first_requirement,
    )
    wheel_metadata = b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    entry_points = (
        b"[console_scripts]\nleika-build-client = leika._client_autobuild:build_client_entrypoint\n"
    )
    members = {
        metadata_name: metadata,
        f"{dist_info}/WHEEL": wheel_metadata,
        f"{dist_info}/entry_points.txt": entry_points,
        **{
            name: b"payload"
            for name in check_wheel.REQUIRED_PACKAGE_FILES | {check_wheel.BUNDLE_NOTICES}
        },
        **{f"{dist_info}/licenses/{name}": b"license" for name in license_files},
    }
    if missing_core_file:
        del members["leika/_server.py"]
    rows = [_record_row(name, payload) for name, payload in members.items()]
    if bad_hash:
        rows[0][1] = "sha256=invalid"
    rows.append([record_name, "", ""])
    record_buffer = io.StringIO()
    csv.writer(record_buffer, lineterminator="\n").writerows(rows)
    members[record_name] = record_buffer.getvalue().encode()

    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)


def _minimal_sdist(
    path: Path,
    *,
    directory_member: str | None = None,
    truncated_notices: bool = False,
    duplicate_name: bool = False,
    omit_first_requirement: bool = False,
    extra_members: tuple[str, ...] = (),
) -> None:
    root = "leika-0.4.0"
    license_files = sorted(check_sdist._expected_license_files())
    license_headers = "".join(f"License-File: {name}\n" for name in license_files)
    pkg_info = _metadata(
        check_sdist,
        "0.4.0",
        license_headers,
        duplicate_name=duplicate_name,
        omit_first_requirement=omit_first_requirement,
    )
    members = {
        "PKG-INFO": pkg_info,
        **{name: b"payload" for name in check_sdist.REQUIRED},
        **{name: b"license" for name in license_files},
    }
    members.update({name: b"transaction debris" for name in extra_members})
    if truncated_notices:
        members[check_sdist.BUNDLE_NOTICE] = b"truncated"
    else:
        notices = "\n".join(check_sdist.REQUIRED_BUNDLE_NOTICE_MARKERS).encode()
        members[check_sdist.BUNDLE_NOTICE] = notices.ljust(
            check_sdist.MIN_BUNDLE_NOTICE_BYTES,
            b"-",
        )
    if directory_member is not None:
        members.pop(directory_member)

    with tarfile.open(path, "w:gz") as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        if directory_member is not None:
            info = tarfile.TarInfo(f"{root}/{directory_member}")
            info.type = tarfile.DIRTYPE
            archive.addfile(info)


def test_wheel_rejects_duplicate_member(tmp_path: Path) -> None:
    wheel = tmp_path / "leika-0.4.0-py3-none-any.whl"
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("duplicate", b"first")
            archive.writestr("duplicate", b"second")

    with zipfile.ZipFile(wheel) as archive:
        with pytest.raises(SystemExit, match="duplicate member"):
            check_wheel._validate_structure(archive, wheel)


def test_wheel_rejects_file_directory_path_collision(tmp_path: Path) -> None:
    wheel = tmp_path / "leika-0.4.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("leika/collision", b"file")
        archive.writestr("leika/collision/", b"")

    with zipfile.ZipFile(wheel) as archive:
        with pytest.raises(SystemExit, match="colliding member paths"):
            check_wheel._validate_structure(archive, wheel)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("leika/Module.py", "leika/module.py"),
        (
            "leika/caf\N{LATIN SMALL LETTER E WITH ACUTE}.py",
            "leika/cafe\N{COMBINING ACUTE ACCENT}.py",
        ),
    ],
)
def test_wheel_rejects_nonportable_path_collision(tmp_path: Path, first: str, second: str) -> None:
    wheel = tmp_path / "leika-0.4.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(first, b"first")
        archive.writestr(second, b"second")

    with zipfile.ZipFile(wheel) as archive:
        with pytest.raises(SystemExit, match="non-portable colliding member paths"):
            check_wheel._validate_structure(archive, wheel)


@pytest.mark.parametrize(
    "member_name",
    ["leika/control\x01.py", "leika/trailing.", "leika/CON.txt", "leika/colon:name.py"],
)
def test_wheel_rejects_nonportable_member_name(tmp_path: Path, member_name: str) -> None:
    wheel = tmp_path / "leika-0.4.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(member_name, b"payload")

    with zipfile.ZipFile(wheel) as archive:
        with pytest.raises(SystemExit, match="non-portable member path"):
            check_wheel._validate_structure(archive, wheel)


def test_archive_portability_predicates_reject_nul() -> None:
    assert check_wheel._has_nonportable_segment("leika/nul\x00name.py")
    assert check_sdist._has_nonportable_segment("leika-0.4.0/nul\x00name.py")


@pytest.mark.parametrize(
    ("ancestor", "descendant"),
    [
        ("leika/file", "leika/file/child.py"),
        ("leika/Module", "leika/module/child.py"),
    ],
)
def test_wheel_rejects_regular_file_ancestor_collision(
    tmp_path: Path, ancestor: str, descendant: str
) -> None:
    wheel = tmp_path / "leika-0.4.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(ancestor, b"file")
        archive.writestr(descendant, b"child")

    with zipfile.ZipFile(wheel) as archive:
        with pytest.raises(SystemExit, match="regular-file ancestor collision"):
            check_wheel._validate_structure(archive, wheel)


def test_wheel_rejects_unsafe_member(tmp_path: Path) -> None:
    wheel = tmp_path / "leika-0.4.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("../escape", b"payload")

    with zipfile.ZipFile(wheel) as archive:
        with pytest.raises(SystemExit, match="unsafe member path"):
            check_wheel._validate_structure(archive, wheel)


def test_wheel_rejects_noncanonical_member(tmp_path: Path) -> None:
    wheel = tmp_path / "leika-0.4.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("leika//module.py", b"payload")

    with zipfile.ZipFile(wheel) as archive:
        with pytest.raises(SystemExit, match="unsafe member path"):
            check_wheel._validate_structure(archive, wheel)


@pytest.mark.parametrize(
    ("member_name", "error"),
    [
        ("rogue.py", "outside package namespaces"),
        ("other-1.0.dist-info/METADATA", "exactly the expected dist-info tree"),
    ],
)
def test_wheel_rejects_foreign_namespace(tmp_path: Path, member_name: str, error: str) -> None:
    wheel = tmp_path / "leika-0.4.0-py3-none-any.whl"
    _minimal_wheel(wheel)
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr(member_name, b"payload")

    with zipfile.ZipFile(wheel) as archive:
        with pytest.raises(SystemExit, match=error):
            check_wheel._validate_structure(archive, wheel)


def test_wheel_rejects_record_hash_mismatch(tmp_path: Path) -> None:
    wheel = tmp_path / "leika-0.4.0-py3-none-any.whl"
    _minimal_wheel(wheel, bad_hash=True)

    with zipfile.ZipFile(wheel) as archive:
        with pytest.raises(SystemExit, match="RECORD hash or size mismatch"):
            check_wheel._validate_structure(archive, wheel)


@pytest.mark.parametrize(
    ("limit_name", "error"),
    [
        ("MAX_WHEEL_MEMBERS", "members"),
        ("MAX_WHEEL_MEMBER_BYTES", "member is too large"),
        ("MAX_WHEEL_UNCOMPRESSED_BYTES", "expands to"),
    ],
)
def test_wheel_rejects_resource_limits_before_decompression(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    error: str,
) -> None:
    wheel = tmp_path / "leika-0.4.0-py3-none-any.whl"
    _minimal_wheel(wheel)
    monkeypatch.setattr(check_wheel, limit_name, 1)

    with zipfile.ZipFile(wheel) as archive:
        with pytest.raises(SystemExit, match=error):
            check_wheel._validate_structure(archive, wheel)


def test_wheel_rejects_symlink_member(tmp_path: Path) -> None:
    wheel = tmp_path / "leika-0.4.0-py3-none-any.whl"
    link = zipfile.ZipInfo("leika/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(link, "target")

    with zipfile.ZipFile(wheel) as archive:
        with pytest.raises(SystemExit, match="symlink or special file"):
            check_wheel._validate_structure(archive, wheel)


def test_wheel_rejects_missing_core_file(tmp_path: Path) -> None:
    wheel = tmp_path / "leika-0.4.0-py3-none-any.whl"
    _minimal_wheel(wheel, missing_core_file=True)

    with zipfile.ZipFile(wheel) as archive:
        with pytest.raises(SystemExit, match="missing required regular file: leika/_server.py"):
            check_wheel._validate_structure(archive, wheel)


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"duplicate_name": True}, "exactly one Name"),
        ({"omit_first_requirement": True}, "Requires-Dist does not match pyproject"),
    ],
)
def test_wheel_rejects_metadata_drift(tmp_path: Path, kwargs: dict[str, bool], error: str) -> None:
    wheel = tmp_path / "leika-0.4.0-py3-none-any.whl"
    _minimal_wheel(wheel, **kwargs)

    with zipfile.ZipFile(wheel) as archive:
        with pytest.raises(SystemExit, match=error):
            check_wheel._validate_structure(archive, wheel)


def test_wheel_rejects_incomplete_license_metadata(tmp_path: Path) -> None:
    wheel = tmp_path / "leika-0.4.0-py3-none-any.whl"
    _minimal_wheel(wheel, missing_license_metadata=True)

    with zipfile.ZipFile(wheel) as archive:
        with pytest.raises(SystemExit, match="License-File entries"):
            check_wheel._validate_structure(archive, wheel)


def test_wheel_main_rejects_symlink_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "target.whl"
    target.write_bytes(b"not a wheel")
    wheel = tmp_path / "leika-0.4.0-py3-none-any.whl"
    try:
        wheel.symlink_to(target)
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")

    monkeypatch.setattr(sys, "argv", ["check_wheel.py", str(wheel)])
    with pytest.raises(SystemExit, match="not a regular file"):
        check_wheel.main()


@pytest.mark.parametrize("member_name", ["../escape", "/absolute"])
def test_sdist_rejects_unsafe_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member_name: str
) -> None:
    sdist = tmp_path / "leika-0.4.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        archive.addfile(tarfile.TarInfo(member_name))

    monkeypatch.setattr(sys, "argv", ["check_sdist.py", str(sdist)])
    with pytest.raises(SystemExit, match="unsafe member path"):
        check_sdist.main()


def test_sdist_rejects_duplicate_member(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sdist = tmp_path / "leika-0.4.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        archive.addfile(tarfile.TarInfo("leika-0.4.0/duplicate"))
        archive.addfile(tarfile.TarInfo("leika-0.4.0/duplicate"))

    monkeypatch.setattr(sys, "argv", ["check_sdist.py", str(sdist)])
    with pytest.raises(SystemExit, match="duplicate member"):
        check_sdist.main()


def test_sdist_rejects_file_directory_path_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sdist = tmp_path / "leika-0.4.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        archive.addfile(tarfile.TarInfo("leika-0.4.0/collision"))
        directory = tarfile.TarInfo("leika-0.4.0/collision/")
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)

    monkeypatch.setattr(sys, "argv", ["check_sdist.py", str(sdist)])
    with pytest.raises(SystemExit, match="duplicate member names"):
        check_sdist.main()


@pytest.mark.parametrize(
    ("ancestor", "descendant"),
    [
        ("file", "file/child.py"),
        ("Module", "module/child.py"),
    ],
)
def test_sdist_rejects_regular_file_ancestor_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ancestor: str,
    descendant: str,
) -> None:
    sdist = tmp_path / "leika-0.4.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        for name in (ancestor, descendant):
            info = tarfile.TarInfo(f"leika-0.4.0/{name}")
            payload = b"payload"
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))

    monkeypatch.setattr(sys, "argv", ["check_sdist.py", str(sdist)])
    with pytest.raises(SystemExit, match="regular-file ancestor collision"):
        check_sdist.main()


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Module.py", "module.py"),
        ("caf\N{LATIN SMALL LETTER E WITH ACUTE}.py", "cafe\N{COMBINING ACUTE ACCENT}.py"),
    ],
)
def test_sdist_rejects_nonportable_path_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first: str,
    second: str,
) -> None:
    sdist = tmp_path / "leika-0.4.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        archive.addfile(tarfile.TarInfo(f"leika-0.4.0/{first}"))
        archive.addfile(tarfile.TarInfo(f"leika-0.4.0/{second}"))

    monkeypatch.setattr(sys, "argv", ["check_sdist.py", str(sdist)])
    with pytest.raises(SystemExit, match="non-portable colliding member paths"):
        check_sdist.main()


@pytest.mark.parametrize(
    "member_name",
    ["control\x01.py", "trailing.", "NUL.txt", "colon:name.py"],
)
def test_sdist_rejects_nonportable_member_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    member_name: str,
) -> None:
    sdist = tmp_path / "leika-0.4.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        archive.addfile(tarfile.TarInfo(f"leika-0.4.0/{member_name}"))

    monkeypatch.setattr(sys, "argv", ["check_sdist.py", str(sdist)])
    with pytest.raises(SystemExit, match="non-portable member path"):
        check_sdist.main()


@pytest.mark.parametrize(
    ("limit_name", "error"),
    [
        ("MAX_SDIST_BYTES", "compressed bytes"),
        ("MAX_SDIST_MEMBERS", "members"),
        ("MAX_SDIST_MEMBER_BYTES", "member is too large"),
        ("MAX_SDIST_UNCOMPRESSED_BYTES", "expands past"),
    ],
)
def test_sdist_rejects_resource_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    error: str,
) -> None:
    sdist = tmp_path / "leika-0.4.0.tar.gz"
    _minimal_sdist(sdist)
    monkeypatch.setattr(check_sdist, limit_name, 1)
    monkeypatch.setattr(sys, "argv", ["check_sdist.py", str(sdist)])
    with pytest.raises(SystemExit, match=error):
        check_sdist.main()


def test_sdist_raw_tar_preflight_bounds_hidden_longname_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sdist = tmp_path / "leika-0.4.0.tar.gz"
    with tarfile.open(sdist, "w:gz", format=tarfile.GNU_FORMAT) as archive:
        archive.addfile(tarfile.TarInfo("leika-0.4.0/" + "a" * 20_000))

    monkeypatch.setattr(check_sdist, "MAX_SDIST_RAW_TAR_BYTES", 1_024)
    monkeypatch.setattr(sys, "argv", ["check_sdist.py", str(sdist)])
    with pytest.raises(SystemExit, match="raw tar expands past"):
        check_sdist.main()


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"duplicate_name": True}, "exactly one Name"),
        ({"omit_first_requirement": True}, "Requires-Dist does not match pyproject"),
    ],
)
def test_sdist_rejects_metadata_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, bool],
    error: str,
) -> None:
    sdist = tmp_path / "leika-0.4.0.tar.gz"
    _minimal_sdist(sdist, **kwargs)

    monkeypatch.setattr(sys, "argv", ["check_sdist.py", str(sdist)])
    with pytest.raises(SystemExit, match=error):
        check_sdist.main()


def test_sdist_main_rejects_symlink_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "target.tar.gz"
    target.write_bytes(b"not an sdist")
    sdist = tmp_path / "leika-0.4.0.tar.gz"
    try:
        sdist.symlink_to(target)
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")

    monkeypatch.setattr(sys, "argv", ["check_sdist.py", str(sdist)])
    with pytest.raises(SystemExit, match="not a regular file"):
        check_sdist.main()


def test_sdist_rejects_declared_license_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sdist = tmp_path / "leika-0.4.0.tar.gz"
    _minimal_sdist(sdist, directory_member="LICENSE")

    monkeypatch.setattr(sys, "argv", ["check_sdist.py", str(sdist)])
    with pytest.raises(SystemExit, match="missing declared license file: LICENSE"):
        check_sdist.main()


def test_sdist_rejects_required_file_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sdist = tmp_path / "leika-0.4.0.tar.gz"
    _minimal_sdist(sdist, directory_member="src/leika/_server.py")

    monkeypatch.setattr(sys, "argv", ["check_sdist.py", str(sdist)])
    with pytest.raises(SystemExit, match="missing: src/leika/_server.py"):
        check_sdist.main()


def test_sdist_requires_tracked_universal_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sdist = tmp_path / "leika-0.4.0.tar.gz"
    _minimal_sdist(sdist, directory_member="uv.lock")

    monkeypatch.setattr(sys, "argv", ["check_sdist.py", str(sdist)])
    with pytest.raises(SystemExit, match="missing: uv.lock"):
        check_sdist.main()


@pytest.mark.parametrize(
    "member_name",
    [
        "src/leika/client/.leika-build-backup/index.html",
        "src/leika/client/.leika-build-stage-deadbeef/index.html",
        "src/leika/.export.leika-backup/index.html",
        "src/leika/.export.leika-stage-deadbeef/index.html",
        "src/leika/.export.leika-transaction",
        "src/leika/.leika-icons-stage-deadbeef/lucide-icons.zip",
    ],
)
def test_sdist_rejects_generated_transaction_debris(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member_name: str
) -> None:
    sdist = tmp_path / "leika-0.4.0.tar.gz"
    _minimal_sdist(sdist, extra_members=(member_name,))

    monkeypatch.setattr(sys, "argv", ["check_sdist.py", str(sdist)])
    with pytest.raises(SystemExit, match="contains generated files"):
        check_sdist.main()


@pytest.mark.parametrize("member_name", ["core", "core.1234"])
def test_sdist_rejects_root_core_dumps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member_name: str
) -> None:
    sdist = tmp_path / "leika-0.4.0.tar.gz"
    _minimal_sdist(sdist, extra_members=(member_name,))

    monkeypatch.setattr(sys, "argv", ["check_sdist.py", str(sdist)])
    with pytest.raises(SystemExit, match="contains generated files"):
        check_sdist.main()


def test_sdist_rejects_links(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sdist = tmp_path / "leika-0.4.0.tar.gz"
    link = tarfile.TarInfo("leika-0.4.0/link")
    link.type = tarfile.SYMTYPE
    link.linkname = "../target"
    with tarfile.open(sdist, "w:gz") as archive:
        archive.addfile(link)

    monkeypatch.setattr(sys, "argv", ["check_sdist.py", str(sdist)])
    with pytest.raises(SystemExit, match="link or special file"):
        check_sdist.main()


def test_sdist_rejects_noncanonical_member(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sdist = tmp_path / "leika-0.4.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        archive.addfile(tarfile.TarInfo("leika-0.4.0/src//module.py"))

    monkeypatch.setattr(sys, "argv", ["check_sdist.py", str(sdist)])
    with pytest.raises(SystemExit, match="unsafe member path"):
        check_sdist.main()


def test_sdist_rejects_truncated_bundle_notices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sdist = tmp_path / "leika-0.4.0.tar.gz"
    _minimal_sdist(sdist, truncated_notices=True)

    monkeypatch.setattr(sys, "argv", ["check_sdist.py", str(sdist)])
    with pytest.raises(SystemExit, match="browser bundle notices are incomplete"):
        check_sdist.main()
