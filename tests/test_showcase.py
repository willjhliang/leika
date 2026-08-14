from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("matplotlib")
pytest.importorskip("plotly")
pytest.importorskip("viser")

showcase = pytest.importorskip("examples.showcase")


class _SetupFailure(RuntimeError):
    pass


class _LoopFailure(RuntimeError):
    pass


class _FakeService:
    def __init__(
        self,
        name: str,
        events: list[tuple[str, bool]],
        stopping: Any,
        *,
        fail_stop: bool = False,
    ) -> None:
        self._name = name
        self._events = events
        self._stopping = stopping
        self._fail_stop = fail_stop

    def stop(self) -> None:
        self._events.append((self._name, self._stopping.is_set()))
        if self._fail_stop:
            raise RuntimeError(f"{self._name} cleanup failed")


def test_showcase_stops_leika_after_partial_setup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, bool]] = []

    def fail_during_viser_setup(lifetime: showcase._ShowcaseLifetime) -> None:
        lifetime.own(
            "Leika server",
            _FakeService("leika", events, lifetime.stopping),
        )
        raise _SetupFailure("Viser setup failed")

    monkeypatch.setattr(showcase, "_run_showcase", fail_during_viser_setup)

    with pytest.raises(_SetupFailure, match="Viser setup failed"):
        showcase.main()

    assert events == [("leika", True)]


def test_showcase_stops_both_services_without_masking_loop_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, bool]] = []

    def fail_in_loop(lifetime: showcase._ShowcaseLifetime) -> None:
        lifetime.own(
            "Leika server",
            _FakeService("leika", events, lifetime.stopping),
        )
        lifetime.own(
            "Viser server",
            _FakeService("viser", events, lifetime.stopping, fail_stop=True),
        )
        raise _LoopFailure("render loop failed")

    monkeypatch.setattr(showcase, "_run_showcase", fail_in_loop)

    with pytest.warns(RuntimeWarning, match="Failed to stop Viser server"):
        with pytest.raises(_LoopFailure, match="render loop failed"):
            showcase.main()

    assert events == [("viser", True), ("leika", True)]


def test_showcase_preserves_keyboard_interrupt_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, bool]] = []

    def interrupt(lifetime: showcase._ShowcaseLifetime) -> None:
        lifetime.own(
            "Leika server",
            _FakeService("leika", events, lifetime.stopping),
        )
        raise KeyboardInterrupt

    monkeypatch.setattr(showcase, "_run_showcase", interrupt)

    showcase.main()

    assert events == [("leika", True)]
