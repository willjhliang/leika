"""How the light/dark scheme gets chosen, end to end.

The scheme is resolved in `App.tsx` and applied as a `dark` or `light` class on
`<html>`; every token in `index.css` and every JS-side color read through
`useColorScheme` hangs off that class, so it is the thing worth asserting on.

`configure_theme` defaults to `theme=None` (equivalent to `"auto"`), which hands the choice to each
browser's `prefers-color-scheme`. These drive that preference through
Playwright's media emulation rather than inspecting rendered colors.
"""

from __future__ import annotations

from typing import Literal

import pytest
from playwright.sync_api import Page, expect

import leika

from .test_settings import choose_theme, open_settings


def wait_for_scheme(page: Page, scheme: str, *, timeout: int = 10_000) -> None:
    """Block until the document root settles on `scheme`."""
    page.wait_for_function(
        "scheme => document.documentElement.classList.contains('dark') === (scheme === 'dark')",
        arg=scheme,
        timeout=timeout,
    )


def open_page(page: Page, server: leika.Server, *, prefers: str) -> None:
    page.emulate_media(color_scheme=prefers)
    page.goto(server.url)
    page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Connecting...')", timeout=15_000
    )


def test_unconfigured_theme_follows_the_browser_preference(
    leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    """A server that never calls `configure_theme` still honors the OS."""
    open_page(page, leika_server, prefers="dark")

    wait_for_scheme(page, "dark")
    assert page_errors == []


@pytest.mark.parametrize("theme", [None, "auto"])
def test_auto_theme_tracks_the_browser_preference(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
    theme: Literal["auto"] | None,
) -> None:
    """Both spellings of Auto follow the OS, and keep following it live."""
    leika_server.gui.configure_theme(theme=theme)
    open_page(page, leika_server, prefers="dark")
    wait_for_scheme(page, "dark")

    # Switching the OS repaints the open page, without a reload.
    page.emulate_media(color_scheme="light")
    wait_for_scheme(page, "light")

    page.emulate_media(color_scheme="dark")
    wait_for_scheme(page, "dark")
    assert page_errors == []


@pytest.mark.parametrize(
    "choice",
    [("dark", "light", "dark"), ("light", "dark", "light")],
    ids=["dark-overrides-light", "light-overrides-dark"],
)
def test_explicit_choice_overrides_the_browser_preference(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
    choice: tuple[Literal["light", "dark"], str, str],
) -> None:
    """`theme="light"` is a decision, not an absence of one."""
    theme, prefers, expected = choice
    leika_server.gui.configure_theme(theme=theme)
    open_page(page, leika_server, prefers=prefers)

    wait_for_scheme(page, expected)
    pane = open_settings(page)
    expect(pane.get_by_role("combobox", name="Theme", exact=True)).to_contain_text(theme.title())
    assert pane.get_by_text("Color scheme", exact=True).count() == 0
    # Auto releases even an explicit choice from Python back to the OS.
    choose_theme(page, pane, "Auto")
    wait_for_scheme(page, prefers)
    choose_theme(page, pane, theme.title())
    wait_for_scheme(page, expected)
    assert page_errors == []


def test_query_parameters_cannot_override_the_scheme(
    leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    """`?darkMode` used to force dark from the URL, ahead of everything else.

    It is gone: the scheme comes from the server, or from the browser when the
    server leaves it on "auto". A stale bookmark carrying the parameter must
    not quietly pin a viewer to a scheme the app did not choose.
    """
    leika_server.gui.configure_theme(theme="light")
    page.emulate_media(color_scheme="dark")
    page.goto(f"{leika_server.url}?darkMode")
    page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)

    wait_for_scheme(page, "light")
    assert page_errors == []


@pytest.mark.parametrize("theme", [None, "auto", "light", "dark"])
def test_live_api_selects_the_theme_and_the_gui_can_change_it_again(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
    theme: Literal["auto", "light", "dark"] | None,
) -> None:
    """Every API call is a setter, even after a viewer changes its last value."""
    leika_server.gui.configure_theme(theme=theme)
    open_page(page, leika_server, prefers="light")
    pane = open_settings(page)
    selection = pane.get_by_role("combobox", name="Theme", exact=True)
    label = (theme or "auto").title()
    expect(selection).to_contain_text(label)
    expected = "dark" if theme == "dark" else "light"
    wait_for_scheme(page, expected)

    # Send the same API value again after a different GUI choice. An effect
    # keyed only by the configured string would miss this second assignment.
    alternate = "Light" if expected == "dark" else "Dark"
    for _ in range(2):
        choose_theme(page, pane, alternate)
        wait_for_scheme(page, alternate.lower())
        leika_server.gui.configure_theme(theme=theme)
        expect(selection).to_contain_text(label)
        wait_for_scheme(page, expected)

    # A later GUI Auto selection must not uncover a server override.
    choose_theme(page, pane, "Auto")
    wait_for_scheme(page, "light")
    page.emulate_media(color_scheme="dark")
    wait_for_scheme(page, "dark")
    assert page_errors == []


def test_api_selection_replaces_a_stored_gui_choice(
    leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    page.add_init_script(
        "localStorage.setItem('leika.settings.v2', JSON.stringify({darkMode: true}))"
    )
    leika_server.gui.configure_theme(theme="light")
    open_page(page, leika_server, prefers="dark")
    wait_for_scheme(page, "light")
    pane = open_settings(page)
    expect(pane.get_by_role("combobox", name="Theme", exact=True)).to_contain_text("Light")
    choose_theme(page, pane, "Dark")
    wait_for_scheme(page, "dark")
    assert page_errors == []
