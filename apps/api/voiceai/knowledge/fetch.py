"""The one fetcher for knowledge pages: scheme, address, redirect, size, type and time limits.

Spec: /architecture/knowledge.md (Safe fetching)

Every request and every redirect hop resolves the host first and refuses loopback, private, link-local, multicast,
reserved and unspecified addresses unless KNOWLEDGE_ALLOW_PRIVATE_URLS is set. The check resolves the name itself;
the HTTP client resolves it again when connecting, so a name that changes its answer between the two lookups is not
caught (DNS rebinding). Hosted deployments should also block private ranges at the network egress.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from voiceai.config import get_settings

USER_AGENT = "VoiceAgentStudio/1.0 (+knowledge indexer)"
ROBOTS_AGENT = "VoiceAgentStudio"
TIMEOUT_S = 10.0
MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5
TEXT_TYPES = ("text/html", "text/plain", "application/xhtml+xml")
XML_TYPES = ("application/xml", "text/xml")  # sitemaps only
METADATA = ipaddress.ip_address("169.254.169.254")


class FetchError(Exception):
    """`code` is one of invalid_url, blocked_address, fetch_failed, unsupported_content, too_large; `status` is the HTTP
    status when the server answered with an error."""

    def __init__(self, code: str, detail: str, status: int | None = None) -> None:
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


@dataclass
class Fetched:
    url: str           # after redirects
    status: int
    content_type: str
    text: str


Resolver = Callable[[str, int], Awaitable[list[str]]]


async def system_resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


# Swappable in tests: a resolver that maps names to addresses, and the HTTP transport (httpx.MockTransport).
resolver: Resolver = system_resolve
transport: httpx.AsyncBaseTransport | None = None


def blocked(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (ip == METADATA or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
            or ip.is_reserved or ip.is_unspecified)


def check_url(url: str) -> tuple[str, int]:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError("invalid_url", "URL must start with http:// or https:// and name a host")
    return parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)


async def check_address(url: str) -> None:
    """Refuse a URL whose host resolves to an internal address (blocked_address), unless private URLs are allowed."""
    host, port = check_url(url)
    if get_settings().knowledge_allow_private_urls:
        return
    try:
        addresses = await resolver(host, port)
    except (OSError, socket.gaierror) as exc:
        raise FetchError("fetch_failed", f"Could not resolve {host}: {exc}") from exc
    if not addresses or any(blocked(a) for a in addresses):
        raise FetchError("blocked_address", f"{host} resolves to an internal address; only public web pages can be imported")


async def fetch(url: str, *, client: httpx.AsyncClient | None = None, accept: tuple[str, ...] = TEXT_TYPES) -> Fetched:
    """GET one page, following at most 5 redirects, each hop checked; raises FetchError."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False, transport=transport,
                                         headers={"User-Agent": USER_AGENT})
    try:
        for _ in range(MAX_REDIRECTS + 1):
            await check_address(url)
            try:
                async with client.stream("GET", url) as resp:
                    if resp.is_redirect and resp.headers.get("location"):
                        url = urljoin(url, resp.headers["location"])
                        continue
                    if resp.status_code >= 400:
                        raise FetchError("fetch_failed", f"HTTP {resp.status_code}", resp.status_code)
                    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                    if ctype and not ctype.startswith(accept):
                        raise FetchError("unsupported_content", f"Not a web page ({ctype})")
                    body = bytearray()
                    async for chunk in resp.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise FetchError("too_large", "Page is larger than 2 MB")
                    text = bytes(body).decode(resp.encoding or "utf-8", errors="replace")
                    return Fetched(url=url, status=resp.status_code, content_type=ctype or "text/html", text=text)
            except httpx.HTTPError as exc:
                raise FetchError("fetch_failed", f"Could not fetch {url}: {exc}") from exc
        raise FetchError("fetch_failed", "Too many redirects")
    finally:
        if own:
            await client.aclose()


def new_client() -> httpx.AsyncClient:
    """A client for several requests in a row (a sync); redirects are followed by fetch() itself."""
    return httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False, transport=transport, headers={"User-Agent": USER_AGENT})
