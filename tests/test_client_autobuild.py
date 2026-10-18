from __future__ import annotations

from pathlib import Path

import pytest

import leika._client_autobuild as autobuild


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    client = tmp_path / "client"
    (client / "src").mkdir(parents=True)
    (client / "src/app.ts").write_text("export const value = 1;\n")
    (client / "package-lock.json").write_text("{}")
    build = client / "build"
    monkeypatch.setattr(autobuild, "client_dir", client)
    monkeypatch.setattr(autobuild, "build_dir", build)
    monkeypatch.setattr(autobuild, "_source_stamp", build / ".leika-sources")
    monkeypatch.setattr(autobuild, "_install_stamp", client / "node_modules/.leika-install")
    monkeypatch.setattr(autobuild, "_lock_path", build / ".leika-build.lock")
    monkeypatch.setattr(autobuild.shutil, "which", lambda name: f"/bin/{name}")
    return client


@pytest.fixture
def npm(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Record npm invocations; a build writes every output into its --outDir."""
    calls: list[list[str]] = []

    def run(command: list[str], *, cwd: Path, check: bool) -> None:
        calls.append(command[1:])
        if command[1] == "ci":
            (cwd / "node_modules").mkdir(exist_ok=True)
        else:
            out_dir = Path(command[command.index("--outDir") + 1])
            for name in autobuild.BUILD_OUTPUTS:
                (out_dir / name).write_text(f"built {name}")

    monkeypatch.setattr(autobuild.subprocess, "run", run)
    return calls


def test_build_installs_only_when_the_lockfile_changes(client: Path, npm: list) -> None:
    autobuild.build_client()
    assert npm == [["ci"], ["run", "build", "--", "--outDir", npm[1][-1]]]
    assert autobuild.is_current()
    assert {path.name for path in (client / "build").iterdir()} == {
        ".leika-build.lock",
        ".leika-sources",
        *autobuild.BUILD_OUTPUTS,
    }

    autobuild.build_client()
    assert len(npm) == 2

    (client / "src/app.ts").write_text("export const value = 2;\n")
    assert not autobuild.is_current()
    autobuild.build_client()
    assert [call[0] for call in npm] == ["ci", "run", "run"]

    (client / "package-lock.json").write_text('{"lockfileVersion": 3}')
    autobuild.build_client()
    assert [call[0] for call in npm] == ["ci", "run", "run", "ci", "run"]


def test_missing_output_is_rebuilt(client: Path, npm: list) -> None:
    autobuild.build_client()
    (client / "build/index.html").unlink()
    assert not autobuild.is_current()
    autobuild.ensure_client_is_built()
    assert (client / "build/index.html").is_file()


def test_failed_build_keeps_the_previous_outputs_and_stamp(
    client: Path, npm: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    autobuild.build_client()
    stamp = (client / "build/.leika-sources").read_text()
    (client / "src/app.ts").write_text("syntax error\n")

    def fail(command: list[str], *, cwd: Path, check: bool) -> None:
        raise autobuild.subprocess.CalledProcessError(2, command)

    monkeypatch.setattr(autobuild.subprocess, "run", fail)
    with pytest.raises(autobuild.subprocess.CalledProcessError):
        autobuild.build_client()
    assert (client / "build/index.html").read_text() == "built index.html"
    assert (client / "build/.leika-sources").read_text() == stamp


def test_installed_package_without_sources_never_builds(client: Path, npm: list) -> None:
    (client / "src/app.ts").unlink()
    (client / "src").rmdir()
    autobuild.ensure_client_is_built()
    assert npm == []


def test_missing_npm_is_a_clear_error(client: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(autobuild.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="needs npm on PATH"):
        autobuild.build_client()
