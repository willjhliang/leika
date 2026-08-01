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
import re
import shutil
import subprocess
import threading
from collections import deque

_SHARE_URL_PATTERN = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

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
    url = match.group(0)
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
        self._url: str | None = None
        self._url_event = threading.Event()
        # Kept for error messages: when cloudflared dies or stalls, its own
        # output is the only useful diagnostic.
        self._recent_lines: deque[str] = deque(maxlen=20)

    @property
    def url(self) -> str | None:
        """Public URL, or None until the tunnel is established."""
        return self._url

    def start(self, timeout: float = 20.0) -> str:
        """Open the tunnel and block until its public URL is known.

        Raises :class:`ShareTunnelError` if cloudflared is missing, exits
        early, or produces no URL within ``timeout`` seconds.
        """
        assert self._process is None
        binary = self._binary if self._binary is not None else shutil.which("cloudflared")
        if binary is None:
            raise ShareTunnelError(_INSTALL_HINT)

        self._process = subprocess.Popen(
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
        )
        # The child is not in our process group's care: without this it would
        # outlive a program that never calls stop().
        atexit.register(self.close)

        threading.Thread(target=self._read_output, daemon=True).start()

        if not self._url_event.wait(timeout) or self._url is None:
            output = "".join(self._recent_lines).strip()
            self.close()
            raise ShareTunnelError(
                f"cloudflared did not report a tunnel URL. Recent output:\n{output}"
            )
        return self._url

    def _read_output(self) -> None:
        process = self._process
        assert process is not None and process.stdout is not None
        for line in process.stdout:
            self._recent_lines.append(line)
            if self._url is None:
                url = find_share_url(line)
                if url is not None:
                    self._url = url
                    self._url_event.set()
        # EOF: the process exited. Wake a start() still waiting so it can
        # report the failure instead of running out its full timeout.
        self._url_event.set()

    def close(self) -> None:
        """Tear the tunnel down. The public URL stops working immediately."""
        atexit.unregister(self.close)
        process = self._process
        if process is None:
            return
        self._process = None
        self._url = None
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
