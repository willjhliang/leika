"""Share tunnels: reach a local leika server from anywhere, no port forwarding.

Built on Cloudflare quick tunnels (the ``cloudflared`` binary): the process
opens an *outbound* connection to Cloudflare's edge and receives a random
public ``https://....trycloudflare.com`` URL that proxies back to the local
port. Outbound-only means it works from behind NATs, firewalls, and VPNs.
Because leika serves its client and websocket on one port, the single tunnel
covers the whole app, and the HTTPS termination at the edge upgrades the
client's websocket to ``wss://`` for free.

The tunnel makes the dashboard publicly reachable, so the server refuses to
share without a password; see ``leika.Server(share=True)``.
"""

from __future__ import annotations

import atexit
import contextlib
import math
import re
import shutil
import subprocess
import threading
from collections import deque

_SHARE_URL_PATTERN = re.compile(
    r"(?<![a-z0-9.-])https://[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.trycloudflare\.com"
    r"(?![a-z0-9.-])",
    re.IGNORECASE,
)

_PROCESS_STOP_TIMEOUT_SECONDS = 5.0
_STARTUP_STABILITY_SECONDS = 0.05

_INSTALL_HINT = (
    "cloudflared was not found on the PATH. Install it with `brew install"
    " cloudflared` (macOS) or see"
    " https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
)


class ShareTunnelError(RuntimeError):
    """Raised when a share tunnel cannot be established."""


def find_share_url(line: str) -> str | None:
    """Extract a quick-tunnel URL from one line of cloudflared output."""
    match = _SHARE_URL_PATTERN.search(line)
    if match is None:
        return None
    url = match.group(0).lower()
    # cloudflared's own registration endpoint, not a tunnel.
    if url == "https://api.trycloudflare.com":
        return None
    return url


class CloudflaredTunnel:
    """Run ``cloudflared`` as a subprocess and report the public URL.

    Args:
        local_port: Local port the tunnel forwards to.
        binary: Path to the cloudflared binary; looked up on the PATH when
            omitted.
    """

    def __init__(self, local_port: int, binary: str | None = None) -> None:
        self._local_port = local_port
        self._binary = binary
        self._process: subprocess.Popen | None = None
        self._started = False
        self._closed = False
        self._state_lock = threading.Lock()
        self._url: str | None = None
        self._url_event = threading.Event()
        # Kept for error messages: when cloudflared dies or stalls, its own
        # output is the only useful diagnostic.
        self._recent_lines: deque[str] = deque(maxlen=20)

    @property
    def url(self) -> str | None:
        """Public URL, or None until the tunnel is established."""
        with self._state_lock:
            return self._url

    def start(self, timeout: float = 20.0) -> str:
        """Open the tunnel and block until its public URL is known.

        Raises :class:`ShareTunnelError` if cloudflared is missing, exits
        early, or produces no URL within ``timeout`` seconds.
        """
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout must be a positive finite number.")
        with self._state_lock:
            if self._started:
                raise RuntimeError(
                    "CloudflaredTunnel instances are one-shot and cannot be restarted."
                )
            self._started = True
        binary = self._binary if self._binary is not None else shutil.which("cloudflared")
        if binary is None:
            raise ShareTunnelError(_INSTALL_HINT)

        try:
            process = subprocess.Popen(
                [
                    binary,
                    "tunnel",
                    "--url",
                    f"http://127.0.0.1:{self._local_port}",
                    "--no-autoupdate",
                ],
                stdout=subprocess.PIPE,
                # cloudflared logs (URL included) go to stderr; fold the streams
                # so one reader sees everything.
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
            )
        except OSError as error:
            raise ShareTunnelError(f"Failed to start cloudflared: {error}") from error
        with self._state_lock:
            closed_during_startup = self._closed
            if not closed_during_startup:
                self._process = process
        if closed_during_startup:
            self._terminate_process(process)
            raise ShareTunnelError("cloudflared tunnel was closed during startup")

        # The child is not in our process group's care: without this it would
        # outlive a program that never calls stop().
        atexit.register(self.close)

        try:
            threading.Thread(target=self._read_output, daemon=True).start()
        except BaseException as error:
            self.close()
            raise ShareTunnelError(f"Failed to start cloudflared output reader: {error}") from error

        if not self._url_event.wait(timeout):
            self.close()
        with self._state_lock:
            process = self._process
            url = self._url
        if process is not None and url is not None:
            try:
                process.wait(timeout=min(float(timeout), _STARTUP_STABILITY_SECONDS))
            except subprocess.TimeoutExpired:
                pass
        with self._state_lock:
            process = self._process
            url = self._url
            output = "".join(self._recent_lines).strip()
        if process is None or process.poll() is not None:
            url = None
        if url is None:
            self.close()
            raise ShareTunnelError(
                f"cloudflared did not report a tunnel URL. Recent output:\n{output}"
            )
        return url

    def _read_output(self) -> None:
        with self._state_lock:
            process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            url = find_share_url(line)
            with self._state_lock:
                self._recent_lines.append(line)
                if not self._closed and self._url is None and url is not None:
                    self._url = url
                    self._url_event.set()
        # EOF means the advertised URL is no longer live. Clear it only if
        # this reader still owns the same process; close() may already have
        # taken ownership for bounded termination.
        with self._state_lock:
            owns_process = self._process is process
            if owns_process:
                self._process = None
                self._url = None
            self._url_event.set()
        if owns_process:
            self._terminate_process(process)

    @staticmethod
    def _terminate_process(process: subprocess.Popen) -> None:
        """Terminate one child without an unbounded wait."""
        if process.poll() is not None:
            return
        with contextlib.suppress(OSError):
            process.terminate()
        try:
            process.wait(timeout=_PROCESS_STOP_TIMEOUT_SECONDS)
            return
        except subprocess.TimeoutExpired:
            pass
        with contextlib.suppress(OSError):
            process.kill()
        try:
            process.wait(timeout=_PROCESS_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            # A killed child should always become waitable, but close() must
            # remain bounded even for a broken Popen stand-in or OS edge case.
            pass

    def close(self) -> None:
        """Tear the tunnel down. The public URL stops working immediately."""
        atexit.unregister(self.close)
        with self._state_lock:
            self._closed = True
            process = self._process
            self._process = None
            self._url = None
            self._url_event.set()
        if process is not None:
            self._terminate_process(process)
