"""
URL utilities shared by the services that write, fetch, and query scraped links.
"""

import ipaddress
import socket
from typing import List, Union
from urllib.parse import urlsplit, urlunsplit

PAGE_SCHEMES = ("http", "https")


class UrlNotAllowed(ValueError):
    """Raised when a URL must not be fetched."""


def normalize_url(url: str) -> str:
    """Canonicalize a URL so one page is always recorded under a single form.

    Stored rows derive their source_url from this and resolve hrefs against it,
    and queries normalize their input the same way, so both sides agree on what
    counts as the same page. Non-page schemes such as mailto: and tel: are
    addresses rather than locations and are returned untouched.
    """
    if not url:
        return url

    parsed = urlsplit(url)
    if parsed.scheme and parsed.scheme.lower() not in PAGE_SCHEMES:
        return url

    if not parsed.netloc:
        parsed = urlsplit(f"https://{url.lstrip('/')}")

    return urlunsplit(
        (
            parsed.scheme.lower() or "https",
            parsed.netloc.lower(),
            parsed.path or "/",
            parsed.query,
            "",
        )
    )


def _resolve(host: str) -> List[Union[ipaddress.IPv4Address, ipaddress.IPv6Address]]:
    """Return every address a host answers with."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as error:
        raise UrlNotAllowed(f"Host {host} could not be resolved") from error

    return [ipaddress.ip_address(info[4][0]) for info in infos]


def assert_fetchable(url: str) -> str:
    """Return the normalized URL, or raise if fetching it would leave the web.

    The scraper fetches whatever a caller hands it, so this is the boundary that
    keeps a request from reaching the private network the services run on: the
    Redis and Postgres containers, localhost, and cloud metadata endpoints are
    all one hostname away otherwise. Names are resolved here rather than at the
    socket, so a host that changes its answer between this check and the fetch
    stays outside what this guard can promise.
    """
    normalized = normalize_url(url)
    parsed = urlsplit(normalized)

    if parsed.scheme not in PAGE_SCHEMES:
        raise UrlNotAllowed(f"Only http and https URLs can be fetched, not {url}")

    if not parsed.hostname:
        raise UrlNotAllowed(f"URL {url} names no host to fetch from")

    for address in _resolve(parsed.hostname):
        if not address.is_global:
            raise UrlNotAllowed(
                f"URL {url} resolves to {address}, which is not a public address"
            )

    return normalized
