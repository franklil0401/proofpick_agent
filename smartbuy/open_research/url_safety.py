"""SSRF-resistant URL policy for official-page extraction.

The policy intentionally fails closed. Tests inject a fake DNS resolver; production
uses the operating system resolver but never accepts an IP literal as input.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from smartbuy.source_search.validator import hostname_allowed, normalize_hostname


Resolver = Callable[[str], Awaitable[list[str]]]


class URLSafetyError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SafeURL:
    url: str
    hostname: str
    resolved_ips: tuple[str, ...]


async def system_resolver(hostname: str) -> list[str]:
    def resolve() -> list[str]:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        return sorted({str(item[4][0]) for item in infos})

    return await asyncio.to_thread(resolve)


def _is_unsafe_ip(raw: str) -> bool:
    try:
        address = ipaddress.ip_address(raw.split("%", 1)[0])
    except ValueError:
        return True
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return bool(
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or not address.is_global
    )


class URLSafetyPolicy:
    def __init__(self, resolver: Resolver | None = None) -> None:
        self._resolver = resolver or system_resolver

    async def validate(self, raw_url: str, allowed_domains: list[str] | tuple[str, ...]) -> SafeURL:
        try:
            parts = urlsplit(raw_url.strip())
        except (TypeError, ValueError) as exc:
            raise URLSafetyError("invalid_url") from exc
        scheme = parts.scheme.casefold()
        if scheme not in {"http", "https"}:
            raise URLSafetyError("scheme_rejected")
        if parts.username is not None or parts.password is not None:
            raise URLSafetyError("userinfo_rejected")
        hostname = normalize_hostname(parts.hostname)
        if not hostname:
            raise URLSafetyError("hostname_invalid")
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            raise URLSafetyError("ip_literal_rejected")
        try:
            port = parts.port
        except ValueError as exc:
            raise URLSafetyError("port_invalid") from exc
        if port is not None and not (
            (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
        ):
            raise URLSafetyError("port_rejected")
        if not hostname_allowed(hostname, allowed_domains):
            raise URLSafetyError("domain_rejected")
        try:
            addresses = await self._resolver(hostname)
        except (OSError, socket.gaierror, TimeoutError) as exc:
            raise URLSafetyError("dns_unavailable") from exc
        if not addresses:
            raise URLSafetyError("dns_empty")
        if any(_is_unsafe_ip(item) for item in addresses):
            raise URLSafetyError("dns_non_public_address")
        authority = hostname
        if port is not None:
            authority = f"{hostname}:{port}"
        query = urlencode(
            [
                (key, value)
                for key, value in parse_qsl(parts.query, keep_blank_values=True)
                if not key.casefold().startswith("utm_")
                and key.casefold()
                not in {"cjdata", "cjevent", "fbclid", "gclid"}
            ],
            doseq=True,
        )
        normalized = urlunsplit((scheme, authority, parts.path or "/", query, ""))
        return SafeURL(url=normalized, hostname=hostname, resolved_ips=tuple(addresses))
