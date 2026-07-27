"""How the light/dark scheme gets chosen, end to end.

The scheme is resolved in `App.tsx` and applied as a `dark` or `light` class on
`<html>`; every token in `index.css` and every JS-side color read through
`useColorScheme` hangs off that class, so it is the thing worth asserting on.

`configure_theme` defaults to `dark_mode="auto"`, which hands the choice to each
browser's `prefers-color-scheme`. These drive that preference through
Playwright's media emulation rather than inspecting rendered colors.
"""

from __future__ import annotations

from playwright.sync_api import Page

import leika


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


def test_auto_theme_follows_a_light_browser_preference(
    leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    leika_server.gui.configure_theme(dark_mode="auto")
    open_page(page, leika_server, prefers="light")

    wait_for_scheme(page, "light")
    assert page_errors == []


def test_auto_theme_tracks_a_mid_session_preference_change(
    leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    """Switching the OS to light repaints the open page, without a reload."""
    open_page(page, leika_server, prefers="dark")
    wait_for_scheme(page, "dark")

    page.emulate_media(color_scheme="light")
    wait_for_scheme(page, "light")

    page.emulate_media(color_scheme="dark")
    wait_for_scheme(page, "dark")
    assert page_errors == []


def test_explicit_dark_mode_overrides_a_light_browser_preference(
    leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    leika_server.gui.configure_theme(dark_mode=True)
    open_page(page, leika_server, prefers="light")

    wait_for_scheme(page, "dark")
    assert page_errors == []


def test_explicit_light_mode_overrides_a_dark_browser_preference(
    leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    """`dark_mode=False` is a decision, not an absence of one."""
    leika_server.gui.configure_theme(dark_mode=False)
    open_page(page, leika_server, prefers="dark")

    wait_for_scheme(page, "light")
    assert page_errors == []


def test_query_parameters_cannot_override_the_scheme(
    leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    """`?darkMode` used to force dark from the URL, ahead of everything else.

    It is gone: the scheme comes from the server, or from the browser when the
    server leaves it on "auto". A stale bookmark carrying the parameter must
    not quietly pin a viewer to a scheme the app did not choose.
    """
    leika_server.gui.configure_theme(dark_mode=False)
    page.emulate_media(color_scheme="dark")
    page.goto(f"{leika_server.url}?darkMode")
    page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)

    wait_for_scheme(page, "light")
    assert page_errors == []
