"""Password gate for the HTTP/websocket server.

Everything leika serves -- the static client and the websocket -- funnels
through one ``process_request`` hook, so a single guard object can protect
both. The guard is transport-agnostic on purpose: it is what keeps a leaked
share URL useless, whether the bytes arrive over localhost or a tunnel.

The ``websockets`` library only parses GET requests, so there is no POST
login form. Instead the login page submits the password as a request header
via ``fetch``, and a successful check answers with a session cookie. The
browser then sends that cookie on every request, including the websocket
handshake.
"""

from __future__ import annotations

import http
import secrets
import time
from collections import deque
from hmac import compare_digest
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import unquote

from websockets.datastructures import Headers
from websockets.http11 import Request, Response

AUTH_PATH = "/auth/session"
COOKIE_NAME = "leika_session"
PASSWORD_HEADER = "x-leika-password"

# Wrong guesses tolerated before the guard stops evaluating passwords for a
# while. Ten in a minute is beyond any human's typos but caps an online
# brute-force at a rate where even a modest password outlives the attacker.
# Global rather than per-client: through a tunnel, addresses are cheap.
MAX_PASSWORD_FAILURES = 10
FAILURE_WINDOW_SECONDS = 60.0

# The client inlines Geist into its single-file build, which sits behind the
# gate, so the login page gets its faces from pre-auth endpoints: Geist for
# the text and Almarai for the brand wordmark, both latin subsets, which
# cover every string the page renders. (Almarai's OFL ships in _licenses.)
FONT_PATH = "/auth/font.woff2"
WORDMARK_FONT_PATH = "/auth/wordmark.woff2"
_FONT_FILES = {
    FONT_PATH: Path(__file__).resolve().parent / "geist-latin-wght-normal.woff2",
    WORDMARK_FONT_PATH: Path(__file__).resolve().parent / "almarai-latin-400.woff2",
}


class HttpPasswordGuard:
    """Gate every HTTP request and websocket handshake behind a password.

    Sessions are a random per-process token handed out as a cookie after a
    correct password; restarting the server signs everyone out. The password
    itself is also accepted directly in the ``x-leika-password`` header
    (URL-encoded), which is what the login page uses and what makes ``curl``
    scripting possible without a cookie jar.

    Guesses are throttled: after ``MAX_PASSWORD_FAILURES`` wrong passwords
    within ``FAILURE_WINDOW_SECONDS``, password evaluation pauses until the
    window drains. The throttle covers every place a password is accepted --
    the login endpoint and the header on any path -- because an attacker gets
    to pick which door to knock on. Session cookies stay unaffected, so a
    lockout never interrupts whoever is already in.
    """

    def __init__(self, password: str) -> None:
        if not password:
            raise ValueError("password must not be empty.")
        self._password = password
        self._session_token = secrets.token_urlsafe(32)
        self._failure_times: deque[float] = deque(maxlen=MAX_PASSWORD_FAILURES)

    def process(self, request: Request) -> Response | None:
        """Check one request. ``None`` means authenticated: let it through."""
        path = request.path.partition("?")[0]
        if path in _FONT_FILES:
            # Pre-auth on purpose: the login page renders in the client's
            # typefaces, and a font discloses nothing about the workspace.
            return _font_response(path)
        if path == AUTH_PATH:
            return self._handle_login(request)
        if self._authenticated(request):
            return None
        if request.headers.get("Upgrade") == "websocket":
            # Rejecting the handshake here (rather than after the upgrade)
            # keeps unauthenticated sockets out of the connection accounting.
            return _plain_response(http.HTTPStatus.UNAUTHORIZED, b"UNAUTHORIZED")
        return Response(
            http.HTTPStatus.UNAUTHORIZED,
            "UNAUTHORIZED",
            Headers(
                **{
                    "Content-Type": "text/html; charset=utf-8",
                    "Cache-Control": "no-store",
                }
            ),
            _LOGIN_PAGE,
        )

    def _handle_login(self, request: Request) -> Response:
        if self._throttled():
            return _plain_response(http.HTTPStatus.TOO_MANY_REQUESTS, b"TOO MANY REQUESTS")
        if not self._password_matches(request):
            return _plain_response(http.HTTPStatus.FORBIDDEN, b"FORBIDDEN")
        cookie = f"{COOKIE_NAME}={self._session_token}; Path=/; HttpOnly; SameSite=Lax"
        # `Secure` only when the browser reached us over TLS (i.e. through a
        # tunnel); over plain http://localhost it would strand the cookie.
        if request.headers.get("X-Forwarded-Proto") == "https":
            cookie += "; Secure"
        return Response(
            http.HTTPStatus.NO_CONTENT,
            "NO CONTENT",
            Headers(**{"Set-Cookie": cookie, "Cache-Control": "no-store"}),
        )

    def _authenticated(self, request: Request) -> bool:
        cookie: SimpleCookie = SimpleCookie()
        # A client may fold cookies into several headers; parse each.
        for header_value in request.headers.get_all("Cookie"):
            cookie.load(header_value)
        morsel = cookie.get(COOKIE_NAME)
        if morsel is not None and compare_digest(morsel.value, self._session_token):
            return True
        return self._password_matches(request)

    def _password_matches(self, request: Request) -> bool:
        header = request.headers.get(PASSWORD_HEADER)
        # No header is anonymous browsing, not a guess: it neither counts
        # toward the throttle nor is blocked by it.
        if header is None:
            return False
        if self._throttled():
            return False
        # URL-encoded so passwords survive the ASCII-only header rules that
        # `fetch` enforces; a no-op for the plain-ASCII common case.
        supplied = unquote(header)
        if compare_digest(supplied.encode(), self._password.encode()):
            self._failure_times.clear()
            return True
        self._failure_times.append(time.monotonic())
        return False

    def _throttled(self) -> bool:
        return (
            len(self._failure_times) == MAX_PASSWORD_FAILURES
            and time.monotonic() - self._failure_times[0] < FAILURE_WINDOW_SECONDS
        )


_font_cache: dict[str, bytes] = {}


def _font_response(path: str) -> Response:
    if path not in _font_cache:
        file = _FONT_FILES[path]
        if not file.is_file():
            return _plain_response(http.HTTPStatus.NOT_FOUND, b"NOT FOUND")
        _font_cache[path] = file.read_bytes()
    payload = _font_cache[path]
    return Response(
        http.HTTPStatus.OK,
        "OK",
        Headers(
            **{
                "Content-Type": "font/woff2",
                "Content-Length": str(len(payload)),
                # The faces change only with a leika release, and a login page
                # that re-fetches tens of KB on every visit helps no one.
                "Cache-Control": "public, max-age=86400",
            }
        ),
        payload,
    )


def _plain_response(status: http.HTTPStatus, body: bytes) -> Response:
    return Response(
        status,
        status.phrase.upper(),
        Headers(
            **{
                "Content-Type": "text/plain; charset=utf-8",
                "Cache-Control": "no-store",
            }
        ),
        body,
    )


# Self-contained on purpose: served before any static asset is reachable, so
# it cannot lean on the client bundle for styling or scripts. Everything below
# nonetheless mirrors the client exactly:
#
# - The design tokens are the client's `index.css` values verbatim (oklch
#   neutrals, `--radius: 0.25rem`, Geist at weights 300/400, 13px text-sm),
#   and the dark palette is the client's `.dark` block.
# - The card, input, button, and error line transcribe the vendored shadcn
#   components' Tailwind recipes into plain CSS: Card's `rounded-xl` +
#   `ring-1 ring-foreground/10` (no border, no drop shadow), Input's and
#   Button's default `h-8 rounded-lg px-2.5` sizes with border-color focus
#   (no focus ring), FieldError's `text-sm font-normal text-destructive`.
# - The theme is decided the way the app decides it: the reader's stored
#   `darkMode` choice (same-origin localStorage) outranks the OS preference,
#   and lands as a `dark` class on <html>, not a media query.
_LOGIN_PAGE = (
    """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>leika</title>
    <script>
      // Before the first paint: the same resolution the app performs, where
      // a viewer who has worked the settings switch outranks the OS.
      (() => {
        let dark = matchMedia("(prefers-color-scheme: dark)").matches;
        try {
          const stored = JSON.parse(localStorage.getItem("leika.settings.v2"));
          if (stored && typeof stored.darkMode === "boolean") dark = stored.darkMode;
        } catch {}
        document.documentElement.classList.toggle("dark", dark);
        document.documentElement.style.colorScheme = dark ? "dark" : "light";
      })();
    </script>
    <style>
      @font-face {
        font-family: "Geist Variable";
        font-style: normal;
        font-display: swap;
        font-weight: 100 900;
        src: url(__FONT_PATH__) format("woff2-variations");
        unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6,
          U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122,
          U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD;
      }
      @font-face {
        font-family: "Almarai";
        font-style: normal;
        font-display: swap;
        font-weight: 400;
        src: url(__WORDMARK_FONT_PATH__) format("woff2");
      }
      :root {
        --background: oklch(1 0 0);
        --foreground: oklch(0.145 0 0);
        --card: oklch(1 0 0);
        --card-foreground: oklch(0.145 0 0);
        --primary: oklch(0.205 0 0);
        --primary-foreground: oklch(0.985 0 0);
        --muted-foreground: oklch(0.556 0 0);
        --destructive: oklch(0.577 0.245 27.325);
        --input: oklch(0.922 0 0);
        --ring: oklch(0.708 0 0);
        --radius: 0.25rem;
      }
      .dark {
        --background: oklch(0.145 0 0);
        --foreground: oklch(0.985 0 0);
        --card: oklch(0.205 0 0);
        --card-foreground: oklch(0.985 0 0);
        --primary: oklch(0.922 0 0);
        --primary-foreground: oklch(0.205 0 0);
        --muted-foreground: oklch(0.708 0 0);
        --destructive: oklch(0.704 0.191 22.216);
        --input: oklch(1 0 0 / 15%);
        --ring: oklch(0.556 0 0);
      }
      * {
        box-sizing: border-box;
      }
      body {
        margin: 0;
        min-height: 100vh;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--background);
        color: var(--foreground);
        /* text-sm at the app's weight-300 normal. */
        font-family: "Geist Variable", sans-serif;
        font-size: 0.8125rem;
        font-weight: 300;
        line-height: 1.4285714;
      }
      /* Card: rounded-xl, ring-1 ring-foreground/10, --card-spacing 1rem.
         Plus the app's shadow-md, which is how its floating panels come off
         the workspace background -- in light mode card and background are
         the same white, and the even glow (one color in both themes, by the
         client's design) is what draws the boundary. */
      form {
        width: min(20rem, calc(100vw - 2rem));
        display: flex;
        flex-direction: column;
        gap: 1rem;
        padding: 1rem 0;
        background: var(--card);
        color: var(--card-foreground);
        border-radius: calc(var(--radius) * 1.4);
        box-shadow:
          0 0 0 1px color-mix(in oklab, var(--foreground) 10%, transparent),
          0 0 8px oklch(0 0 0 / 0.16);
      }
      /* CardHeader: grid gap-1 px-(--card-spacing). */
      header {
        display: grid;
        gap: 0.25rem;
        padding: 0 1rem;
      }
      /* The brand lockup, as the docs compose it (leika.css): the bloom and
         the Almarai wordmark side by side, centered on each other, with the
         logo and gap measured off the wordmark's type size. Sized at the
         sidebar-brand scale rather than the homepage masthead's. */
      #title {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 0.1875em;
        font-family: "Almarai", "Geist Variable", sans-serif;
        font-size: 1.5rem;
        font-weight: 400;
        letter-spacing: -0.03em;
        margin-bottom: 0.25rem;
      }
      #title svg {
        width: 1.275em;
        height: auto;
      }
      /* CardDescription: text-sm text-muted-foreground. */
      #description {
        margin: 0;
        color: var(--muted-foreground);
      }
      #content {
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
        padding: 0 1rem;
      }
      /* Input: h-8 rounded-lg border-input bg-transparent px-2.5 py-1,
         border-color focus. */
      input {
        height: 2rem;
        width: 100%;
        min-width: 0;
        border-radius: var(--radius);
        border: 1px solid var(--input);
        background: transparent;
        padding: 0.25rem 0.625rem;
        font: inherit;
        color: inherit;
        outline: none;
        transition:
          color 0.15s cubic-bezier(0.4, 0, 0.2, 1),
          background-color 0.15s cubic-bezier(0.4, 0, 0.2, 1),
          border-color 0.15s cubic-bezier(0.4, 0, 0.2, 1);
      }
      input::placeholder {
        color: var(--muted-foreground);
      }
      input:focus-visible {
        border-color: var(--ring);
      }
      .dark input {
        background: color-mix(in oklab, var(--input) 30%, transparent);
      }
      /* Button, default variant and size: h-8 rounded-lg px-2.5 font-medium
         bg-primary, hover 80% fill, active down a pixel. */
      button {
        height: 2rem;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 0.375rem;
        padding: 0 0.625rem;
        border-radius: var(--radius);
        border: 1px solid transparent;
        background: var(--primary) padding-box;
        color: var(--primary-foreground);
        font: inherit;
        font-weight: 400;
        white-space: nowrap;
        user-select: none;
        cursor: default;
        outline: none;
        transition: all 0.15s cubic-bezier(0.4, 0, 0.2, 1);
      }
      button:hover {
        background: color-mix(in oklab, var(--primary) 80%, transparent) padding-box;
      }
      button:active {
        transform: translateY(1px);
      }
      button:focus-visible {
        border-color: var(--ring);
      }
      /* A wrong password shakes the button instead of printing an error:
         there is only one field, so nothing else needs pointing at. The
         amplitude decays so the motion reads as a headshake, not a buzz. */
      @keyframes shake {
        0%,
        100% {
          transform: translateX(0);
        }
        20% {
          transform: translateX(-5px);
        }
        40% {
          transform: translateX(5px);
        }
        60% {
          transform: translateX(-3px);
        }
        80% {
          transform: translateX(2px);
        }
      }
      button.shake {
        animation: shake 0.4s cubic-bezier(0.4, 0, 0.2, 1);
      }
    </style>
  </head>
  <body>
    <form id="form">
      <header>
        <div id="title">
          <!-- The leika bloom (docs/_static/leika.svg): six petals blended
               with `screen`, so overlaps mix additively. `isolation` keeps
               the blending self-contained, so it renders the same on either
               theme's card. -->
          <svg viewBox="2.5 0 357 357" aria-hidden="true">
            <defs>
              <path id="p0" d="M180.955 194.727C210.082 194.727 233.694 151.136 233.694 97.3637C233.694 43.5912 210.082 6.10352e-05 180.955 6.10352e-05C151.828 6.10352e-05 128.216 43.5912 128.216 97.3637C128.216 151.136 151.828 194.727 180.955 194.727Z"/>
              <path id="p1" d="M166.902 186.614C181.465 211.838 231.022 210.491 277.59 183.605C324.159 156.719 350.104 114.474 335.54 89.25C320.977 64.0255 271.42 65.3726 224.852 92.2588C178.283 119.145 152.338 161.389 166.902 186.614Z"/>
              <path id="p2" d="M166.902 170.386C152.338 195.611 178.283 237.855 224.852 264.741C271.42 291.627 320.977 292.975 335.54 267.75C350.104 242.526 324.159 200.281 277.59 173.395C231.022 146.509 181.465 145.162 166.902 170.386Z"/>
              <path id="p3" d="M180.955 162.273C151.828 162.273 128.216 205.864 128.216 259.636C128.216 313.409 151.828 357 180.955 357C210.082 357 233.694 313.409 233.694 259.636C233.694 205.864 210.082 162.273 180.955 162.273Z"/>
              <path id="p4" d="M195.008 170.386C180.445 145.162 130.888 146.509 84.3195 173.395C37.7512 200.282 11.8061 242.526 26.3694 267.75C40.9328 292.975 90.4898 291.628 137.058 264.741C183.626 237.855 209.572 195.611 195.008 170.386Z"/>
              <path id="p5" d="M195.008 186.614C209.571 161.389 183.626 119.145 137.058 92.2588C90.4897 65.3726 40.9327 64.0255 26.3693 89.25C11.8059 114.474 37.7511 156.719 84.3194 183.605C130.888 210.491 180.445 211.838 195.008 186.614Z"/>
            </defs>
            <g style="isolation:isolate">
              <use href="#p0" fill="#FF2D1F" style="mix-blend-mode:screen"/>
              <use href="#p1" fill="#22E06A" style="mix-blend-mode:screen"/>
              <use href="#p2" fill="#3B82FF" style="mix-blend-mode:screen"/>
              <use href="#p3" fill="#FF2D1F" style="mix-blend-mode:screen"/>
              <use href="#p4" fill="#22E06A" style="mix-blend-mode:screen"/>
              <use href="#p5" fill="#3B82FF" style="mix-blend-mode:screen"/>
            </g>
          </svg>
          leika
        </div>
        <p id="description">This dashboard is password protected.</p>
      </header>
      <div id="content">
        <input
          id="password"
          type="password"
          placeholder="Password"
          autocomplete="current-password"
          autofocus
        />
        <button type="submit">Unlock</button>
      </div>
    </form>
    <script>
      document.getElementById("form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const password = document.getElementById("password").value;
        const response = await fetch("__AUTH_PATH__", {
          headers: { "__PASSWORD_HEADER__": encodeURIComponent(password) },
        });
        if (response.status === 204) {
          location.reload();
        } else {
          const button = document.querySelector("button");
          // Restart the animation even when it is already mid-shake.
          button.classList.remove("shake");
          void button.offsetWidth;
          button.classList.add("shake");
        }
      });
    </script>
  </body>
</html>
""".replace("__FONT_PATH__", FONT_PATH)
    .replace("__WORDMARK_FONT_PATH__", WORDMARK_FONT_PATH)
    .replace("__AUTH_PATH__", AUTH_PATH)
    .replace("__PASSWORD_HEADER__", PASSWORD_HEADER)
    .encode()
)
