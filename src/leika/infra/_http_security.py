"""HTTP endpoint identity and response policy, independent of server lifecycle."""

from __future__ import annotations

import dataclasses
import http
import ipaddress
import itertools
import json
import os
import threading
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

from websockets import Headers
from websockets.http11 import Request

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    # Prevent another LAN origin from embedding passwordless media/static
    # responses through no-CORS element loads. Same-origin workspace assets
    # and direct top-level navigation remain available.
    "Cross-Origin-Resource-Policy": "same-origin",
}


def _canonical_hostname(host: str) -> str | None:
    """Normalize one DNS or IP host without accepting authority syntax."""
    if (
        not host
        or host != host.strip()
        or any(ord(c) < 33 or ord(c) == 127 for c in host)
        or any(c in host for c in "/?#@,[]*")
    ):
        return None
    candidate = host[:-1] if host.endswith(".") else host
    candidate = candidate.replace("%25", "%")
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        if ":" in candidate or "%" in candidate:
            return None
        try:
            normalized = candidate.encode("idna").decode("ascii").lower()
        except UnicodeError:
            return None
        labels = normalized.split(".")
        if not normalized or len(normalized) > 253:
            return None
        for label in labels:
            if (
                not 1 <= len(label) <= 63
                or not label[0].isalnum()
                or not label[-1].isalnum()
                or any(not (c.isdigit() or "a" <= c <= "z" or c == "-") for c in label)
            ):
                return None
        return normalized
    return str(address).lower()


def _parse_authority(authority: str, scheme: str) -> tuple[str, str, int] | None:
    """Parse a Host-style authority into a comparable origin tuple."""
    if not authority or authority != authority.strip() or any(c.isspace() for c in authority):
        return None
    if "," in authority or (authority.count(":") > 1 and not authority.startswith("[")):
        return None
    try:
        parsed = urlsplit(f"{scheme}://{authority}")
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.path != ""
        or parsed.query
        or parsed.fragment
    ):
        return None
    host = _canonical_hostname(parsed.hostname or "")
    if host is None:
        return None
    return scheme, host, port if port is not None else (443 if scheme == "https" else 80)


def _parse_origin(origin: str) -> tuple[str, str, int] | None:
    """Parse an HTTP browser Origin, rejecting opaque and malformed values."""
    if not origin or origin != origin.strip() or any(c.isspace() for c in origin):
        return None
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in ("http", "https")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != ""
        or parsed.query
        or parsed.fragment
    ):
        return None
    host = _canonical_hostname(parsed.hostname or "")
    if host is None:
        return None
    return (
        parsed.scheme,
        host,
        port if port is not None else (443 if parsed.scheme == "https" else 80),
    )


_ALLOWED_HOSTS_MAX = 256


def _normalize_allowed_hosts(hosts: Sequence[str] | None) -> frozenset[str]:
    if hosts is None:
        return frozenset()
    if isinstance(hosts, str) or not isinstance(hosts, Sequence):
        raise TypeError("allowed_hosts must be a sequence of host names, not one string.")
    reported_length = len(hosts)
    if reported_length > _ALLOWED_HOSTS_MAX:
        raise ValueError(f"allowed_hosts cannot contain more than {_ALLOWED_HOSTS_MAX} entries.")
    materialized = tuple(itertools.islice(iter(hosts), _ALLOWED_HOSTS_MAX + 1))
    if len(materialized) != reported_length:
        raise ValueError("allowed_hosts length changed during validation.")
    normalized: set[str] = set()
    for host in materialized:
        if not isinstance(host, str):
            raise TypeError("allowed_hosts entries must be strings.")
        canonical = _canonical_hostname(host)
        if canonical is None:
            raise ValueError(f"Invalid allowed host: {host!r}.")
        if canonical in normalized:
            raise ValueError(f"Duplicate allowed host: {host!r}.")
        normalized.add(canonical)
    return frozenset(normalized)


def _configured_allowed_hosts(hosts: Sequence[str] | None) -> frozenset[str]:
    """Use the user's persistent endpoint names unless the caller overrides them.

    Missing configuration preserves the default localhost/IP policy. An existing
    but invalid or unreadable file fails startup rather than silently discarding
    the operator's configuration. Explicit sequences (including []) are complete
    overrides, so applications can opt out of user configuration.
    """
    if hosts is not None:
        return _normalize_allowed_hosts(hosts)
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home) if config_home else Path.home() / ".config"
    if not base.is_absolute():
        raise ValueError("XDG_CONFIG_HOME must be an absolute path.")
    path = base / "leika" / "allowed_hosts.json"
    try:
        payload = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return frozenset()
    except (OSError, UnicodeError) as error:
        raise ValueError(f"Cannot read Leika allowed hosts from {path}: {error}") from error
    try:
        values = json.loads(payload)
        if not isinstance(values, list):
            raise TypeError("expected a JSON array of hostnames")
        return _normalize_allowed_hosts(values)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid Leika allowed hosts in {path}: {error}") from error


def _is_ip_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _direct_host_allowed(request_host: str, bind_host: str, allowed: frozenset[str]) -> bool:
    if request_host in allowed:
        return True
    bind = _canonical_hostname(bind_host)
    try:
        wildcard_bind = bind is not None and ipaddress.ip_address(bind).is_unspecified
    except ValueError:
        wildcard_bind = False
    if wildcard_bind:
        return _is_ip_host(request_host) or request_host == "localhost"
    if bind is None:
        return False
    if _is_loopback_host(bind):
        return _is_loopback_host(request_host)
    return request_host == bind


def _first_forwarded_value(headers: Headers, name: str) -> str | None:
    values = headers.get_all(name)
    if len(values) != 1:
        return None
    if "," in values[0]:
        return None
    return values[0].strip() or None


@dataclasses.dataclass(frozen=True)
class _RequestAddress:
    origin: tuple[str, str, int]
    secure: bool


def _request_address(
    request: Request,
    *,
    bind_host: str,
    allowed_hosts: frozenset[str],
    trusted_proxy_hosts: frozenset[str],
) -> _RequestAddress | None:
    """Validate Host/proxy/Origin and return the browser-visible origin."""
    hosts = request.headers.get_all("Host")
    if len(hosts) != 1:
        return None
    direct = _parse_authority(hosts[0], "http")
    if direct is None:
        return None

    forwarded_protos = request.headers.get_all("X-Forwarded-Proto")
    forwarded_hosts = request.headers.get_all("X-Forwarded-Host")
    if forwarded_hosts and not forwarded_protos:
        return None
    if forwarded_protos:
        proto = _first_forwarded_value(request.headers, "X-Forwarded-Proto")
        if proto != "https" or direct[1] not in trusted_proxy_hosts:
            return None
        if forwarded_hosts:
            forwarded_host = _first_forwarded_value(request.headers, "X-Forwarded-Host")
            forwarded = (
                _parse_authority(forwarded_host, proto) if forwarded_host is not None else None
            )
            if (
                forwarded is None
                or forwarded[1] != direct[1]
                or forwarded[1] not in trusted_proxy_hosts
                or forwarded[2] != 443
            ):
                return None
        effective = ("https", direct[1], 443)
    else:
        if not _direct_host_allowed(direct[1], bind_host, allowed_hosts):
            return None
        effective = direct

    origins = request.headers.get_all("Origin")
    if len(origins) > 1 or (origins and _parse_origin(origins[0]) != effective):
        return None
    return _RequestAddress(effective, secure=effective[0] == "https")


def _add_security_headers(
    status: http.HTTPStatus, headers: Headers, *, allow_embedding: bool
) -> None:
    # websockets serves ordinary HTTP as a rejected opening handshake and
    # closes the transport after the response. Spell that contract explicitly
    # so clients never attempt a second request against the same reservation.
    if status != http.HTTPStatus.SWITCHING_PROTOCOLS:
        if "Connection" in headers:
            del headers["Connection"]
        headers["Connection"] = "close"
    if not allow_embedding:
        headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
    for name, value in _SECURITY_HEADERS.items():
        headers.setdefault(name, value)


class HttpRequestPolicy:
    """Validate browser endpoints and track explicitly trusted proxy hosts."""

    def __init__(
        self, bind_host: str, allowed_hosts: frozenset[str], *, allow_embedding: bool
    ) -> None:
        self._bind_host = bind_host
        self._allowed_hosts = allowed_hosts
        self._allow_embedding = allow_embedding
        self._trusted_proxy_hosts: frozenset[str] = frozenset()
        self._trusted_proxy_lock = threading.Lock()

    def trust_proxy_host(self, host: str) -> None:
        canonical = _canonical_hostname(host)
        if canonical is None:
            raise ValueError(f"Invalid trusted proxy host: {host!r}.")
        with self._trusted_proxy_lock:
            self._trusted_proxy_hosts = self._trusted_proxy_hosts | {canonical}

    def address(self, request: Request) -> _RequestAddress | None:
        with self._trusted_proxy_lock:
            trusted_proxy_hosts = self._trusted_proxy_hosts
        return _request_address(
            request,
            bind_host=self._bind_host,
            allowed_hosts=self._allowed_hosts,
            trusted_proxy_hosts=trusted_proxy_hosts,
        )

    def secure_headers(self, status: http.HTTPStatus, headers: Headers) -> None:
        _add_security_headers(status, headers, allow_embedding=self._allow_embedding)
