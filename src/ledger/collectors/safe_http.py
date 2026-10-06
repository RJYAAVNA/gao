"""Pinned public HTTPS transport; no proxy, redirects or DNS rebinding bypass."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit

MAX_BYTES = 5 * 1024 * 1024


class FetchError(ValueError):
    pass


def public_addresses(hostname: str) -> list[str]:
    addresses = list(
        dict.fromkeys(
            info[4][0] for info in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        )
    )
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise FetchError("blocked_address")
    return addresses


def validate_url(url: str, allowed: set[str]) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.fragment
        or not parsed.hostname
        or parsed.hostname.lower() not in allowed
        or "\\" in url
    ):
        raise FetchError("unapproved_url")
    return parsed.hostname.lower()


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, hostname: str, address: str, timeout: float) -> None:
        self.tls_context = ssl.create_default_context()
        super().__init__(hostname, timeout=timeout, context=self.tls_context)
        self.address = address

    def connect(self) -> None:
        raw = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            peer = raw.getpeername()[0]
            if not ipaddress.ip_address(peer).is_global:
                raise FetchError("blocked_peer")
            self.sock = self.tls_context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def fetch_public(
    url: str,
    allowed: set[str],
    method: str = "GET",
    body: bytes | None = None,
    deadline: float | None = None,
) -> bytes:
    deadline = deadline or time.monotonic() + 60
    for _ in range(4):
        hostname = validate_url(url, allowed)
        addresses = public_addresses(hostname)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FetchError("timeout")
        conn = PinnedHTTPS(hostname, addresses[0], min(30, remaining))
        try:
            parsed = urlsplit(url)
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            conn.request(
                method,
                path,
                body=body,
                headers={
                    "Accept-Encoding": "identity",
                    "Accept": "application/json,text/html",
                    "Content-Type": "application/json",
                    "User-Agent": "WealthLedger/2.0",
                },
            )
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise FetchError("invalid_redirect")
                url = urljoin(url, location)
                if response.status == 303:
                    method, body = "GET", None
                continue
            if response.status != 200:
                raise FetchError(
                    "rate_limited"
                    if response.status == 429
                    else "server_error"
                    if response.status >= 500
                    else "http_error"
                )
            if response.getheader("Content-Encoding", "identity") != "identity":
                raise FetchError("compressed_response_not_supported")
            data = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FetchError("timeout")
                if conn.sock:
                    conn.sock.settimeout(min(30, remaining))
                chunk = response.read1(min(65536, MAX_BYTES + 1 - len(data)))
                if not chunk:
                    return bytes(data)
                data.extend(chunk)
                if len(data) > MAX_BYTES:
                    raise FetchError("response_too_large")
        finally:
            conn.close()
    raise FetchError("too_many_redirects")
