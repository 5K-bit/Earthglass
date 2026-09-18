"""Bounded public HTTPS acquisition, with DNS pinning and no redirects."""

from __future__ import annotations

import ipaddress
import json
import socket
import threading
import time
from urllib.parse import urlsplit

import httpx


class ProviderError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def public_address(host, resolver=socket.getaddrinfo):
    try:
        addresses = {
            item[4][0] for item in resolver(host, 443, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise ProviderError(
            "dns_unavailable", "Provider name could not be resolved"
        ) from exc
    if not addresses or any(
        not ipaddress.ip_address(address).is_global for address in addresses
    ):
        raise ProviderError("unsafe_address", "Provider address is not public")
    return sorted(addresses, key=lambda item: (":" in item, item))[0]


class PublicHTTP:
    def __init__(
        self,
        *,
        timeout=10.0,
        max_bytes=8 * 1024**2,
        resolver=socket.getaddrinfo,
        transport_factory=None,
    ):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.resolver = resolver
        self.transport_factory = transport_factory
        self.offline = False
        self._clients = {}
        self._lock = threading.Lock()
        self._cache = {}
        self._cache_locks = {}

    def bytes(
        self, url, *, params=None, method="GET", data=None, headers=None, max_bytes=None
    ):
        self._require_online()
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.port not in (None, 443)
        ):
            raise ProviderError(
                "unsafe_url", "Only public HTTPS provider endpoints are allowed"
            )
        address = public_address(parts.hostname, self.resolver)
        with self._lock:
            self._require_online()
            if parts.hostname not in self._clients:
                transport = self.transport_factory() if self.transport_factory else None
                self._clients[parts.hostname] = httpx.Client(
                    timeout=httpx.Timeout(self.timeout, connect=min(self.timeout, 5)),
                    follow_redirects=False,
                    transport=transport,
                    trust_env=False,
                    limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
                )
            client = self._clients[parts.hostname]
        request_url = httpx.URL(url).copy_with(host=address)
        request_headers = {
            "User-Agent": "OBEOS-EarthGlass/1.0 (+local spatial workspace)",
            **(headers or {}),
            "Host": parts.hostname,
        }
        limit = min(max_bytes or self.max_bytes, self.max_bytes)
        deadline = time.monotonic() + self.timeout
        try:
            self._require_online()
            with client.stream(
                method,
                request_url,
                params=params,
                data=data,
                headers=request_headers,
                extensions={"sni_hostname": parts.hostname},
            ) as response:
                if response.status_code == 429:
                    raise ProviderError(
                        "rate_limited", "Provider quota reached; retry is delayed"
                    )
                if response.status_code in (401, 403):
                    raise ProviderError(
                        "access_denied", "Provider access or credential is unavailable"
                    )
                if 300 <= response.status_code < 400:
                    raise ProviderError(
                        "redirect_rejected",
                        "Provider redirected outside the configured request",
                    )
                if response.status_code >= 400:
                    raise ProviderError(
                        "upstream_error",
                        f"Provider returned HTTP {response.status_code}",
                    )
                chunks = []
                size = 0
                for chunk in response.iter_bytes():
                    self._require_online()
                    if time.monotonic() > deadline:
                        raise ProviderError(
                            "timeout", "Provider exceeded its total request deadline"
                        )
                    size += len(chunk)
                    if size > limit:
                        raise ProviderError(
                            "response_too_large",
                            "Provider response exceeded its byte limit",
                        )
                    chunks.append(chunk)
                return b"".join(chunks), response.headers.get(
                    "content-type", "application/octet-stream"
                )
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", "Provider request timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                "connection_error", "Provider connection failed"
            ) from exc

    def _require_online(self):
        if self.offline:
            raise ProviderError("offline_mode", "Offline mode; public updates are paused")

    def json(self, url, *, cache_ttl=0, **kwargs):
        if cache_ttl:
            import hashlib

            key = hashlib.sha256(
                json.dumps([url, kwargs], sort_keys=True).encode()
            ).hexdigest()
            with self._lock:
                entry = self._cache.get(key)
                if entry and entry[0] > time.monotonic():
                    return json.loads(entry[1])
                lock = self._cache_locks.setdefault(key, threading.Lock())
            with lock:
                with self._lock:
                    entry = self._cache.get(key)
                    if entry and entry[0] > time.monotonic():
                        return json.loads(entry[1])
                payload, _ = self.bytes(url, **kwargs)
                try:
                    value = json.loads(payload)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise ProviderError(
                        "invalid_json", "Provider returned invalid JSON"
                    ) from exc
                with self._lock:
                    self._cache[key] = (
                        time.monotonic() + min(cache_ttl, 3600),
                        payload,
                    )
                    while (
                        sum(len(entry[1]) for entry in self._cache.values())
                        > 32 * 1024**2
                        or len(self._cache) > 32
                    ):
                        oldest = next(iter(self._cache))
                        del self._cache[oldest]
                    # Locks have no payload and are bounded to the recent request set.
                    if len(self._cache_locks) > 64:
                        self._cache_locks = {
                            k: v
                            for k, v in self._cache_locks.items()
                            if v.locked() or k in self._cache
                        }
                return value
        payload, _ = self.bytes(url, **kwargs)
        try:
            return json.loads(payload)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ProviderError(
                "invalid_json", "Provider returned invalid JSON"
            ) from exc

    def text(self, url, **kwargs):
        payload, _ = self.bytes(url, **kwargs)
        try:
            return payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ProviderError(
                "invalid_text", "Provider text encoding is invalid"
            ) from exc

    def close(self):
        with self._lock:
            clients, self._clients = list(self._clients.values()), {}
        for client in clients:
            client.close()
