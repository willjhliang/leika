from __future__ import annotations

from collections.abc import Generator

import pytest
from playwright.sync_api import Page

import leika
import leika._client_autobuild

from .utils import find_free_port


@pytest.fixture()
def browser_context_args(browser_context_args: dict) -> dict:
    return {
        **browser_context_args,
        "viewport": {"width": 960, "height": 700},
        "device_scale_factor": 1,
        "reduced_motion": "reduce",
    }


@pytest.fixture(scope="session", autouse=True)
def _build_client_once() -> None:
    """Build the client once for the session, then stop each server rechecking.

    These tests are served `client/build`, never the dev server, so a stale
    build silently tests old code -- and the build is skipped exactly when it
    is most likely to be stale, since `ensure_client_is_built` steps aside
    while `npm run dev` holds the sources. Build here, ignoring that, and
    no-op the per-server check so the ~90 servers this suite starts do not
    each pay for it.
    """
    leika._client_autobuild.ensure_client_is_built(ignore_dev_server=True)
    leika._client_autobuild.ensure_client_is_built = lambda: None


@pytest.fixture()
def leika_server(request: pytest.FixtureRequest) -> Generator[leika.Server, None, None]:
    port = find_free_port()
    server = leika.Server(
        host="127.0.0.1",
        port=port,
        workspace_id=request.node.name,
        verbose=False,
    )
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def page_errors(page: Page) -> list[str]:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    return errors


@pytest.fixture()
def leika_page(page: Page, leika_server: leika.Server, page_errors: list[str]) -> Page:
    del page_errors
    page.goto(leika_server.url)
    page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Connecting...')", timeout=15_000
    )
    return page
