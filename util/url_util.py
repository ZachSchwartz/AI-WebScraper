"""
URL utilities shared by the services that write and query scraped links.
"""

from urllib.parse import urlsplit, urlunsplit

PAGE_SCHEMES = ("http", "https")


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
