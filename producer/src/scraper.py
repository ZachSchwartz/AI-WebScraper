"""
Web scraper module for collecting data from target websites.
"""

import time
import re
import logging
from typing import Dict, List, Any, Optional, Sequence, Set, Union
from urllib.robotparser import RobotFileParser
from urllib.parse import urlparse, urljoin
import requests
from bs4 import BeautifulSoup, Tag

from util.error_util import format_error
from util.url_util import UrlNotAllowed, assert_fetchable

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


MAX_REDIRECTS = 5
PUBLIC_SUFFIX_LABELS = {"com", "org", "net", "edu", "gov", "io", "co", "uk"}
GENERIC_PATH_WORDS = {"index", "home", "page", "default"}
UNINFORMATIVE_REL = {"nofollow", "noopener"}
MIN_DESCRIPTION_LENGTH = 10
MAX_DESCRIPTION_LENGTH = 300
HEADING_TAGS = ["h1", "h2", "h3"]
CONTEXT_TAGS = ["p", *HEADING_TAGS, "li"]
DEFAULT_TIMEOUT = 30
DEFAULT_RETRY_COUNT = 3
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)


def is_allowed_by_robots(url: str, user_agent: str) -> bool:
    """Check whether robots.txt permits fetching the URL.

    A site that serves no reachable robots.txt is stating no restriction, so a
    transport failure reading it is treated as permission rather than refusal.
    RobotFileParser already maps the status codes that do carry meaning: 4xx
    allows everything, 5xx allows nothing.
    """
    parser = RobotFileParser()
    parser.set_url(urljoin(url, "/robots.txt"))
    try:
        parser.read()
    except OSError as error:
        logger.info("No readable robots.txt for %s: %s", url, error)
        return True

    return parser.can_fetch(user_agent, url)


def fetch_page(url: str, headers: Dict[str, str], timeout: int) -> requests.Response:
    """Fetch a URL, checking every redirect hop before following it.

    requests follows redirects on its own, which would let a public URL bounce
    the fetch onto the private network assert_fetchable exists to keep it off.

    Raises:
        UrlNotAllowed: if a hop leaves the public web or the chain never ends.
    """
    location = url
    for _ in range(MAX_REDIRECTS):
        response = requests.get(
            location, headers=headers, timeout=timeout, allow_redirects=False
        )
        if not response.is_redirect:
            return response

        location = assert_fetchable(
            urljoin(location, response.headers.get("Location", ""))
        )

    raise UrlNotAllowed(f"URL {url} redirected more than {MAX_REDIRECTS} times")


def fetch_with_requests(
    url: str, headers: Dict[str, str], timeout: int, retry_count: int
) -> Optional[Dict[str, Any]]:
    """Fetch URL content, backing off exponentially between failed attempts."""
    if not is_allowed_by_robots(url, headers["User-Agent"]):
        logger.info("Skipping %s (disallowed by robots.txt)", url)
        return format_error(
            "robots_txt_error",
            f"This website's robots.txt file does not allow scraping {url}",
            url,
        )

    for attempt in range(retry_count):
        try:
            response = fetch_page(url, headers, timeout)
            response.raise_for_status()
            if not response.text:
                return format_error(
                    "empty_response", f"Received empty response from {url}", url
                )
            return {"content": response.text}
        except UrlNotAllowed as e:
            logger.warning("Refusing to follow %s: %s", url, e)
            return format_error("url_not_allowed", str(e), url)
        except requests.exceptions.RequestException as e:
            logger.warning(
                "Attempt %d/%d failed for %s: %s", attempt + 1, retry_count, url, e
            )
            if attempt == retry_count - 1:
                return format_error(
                    "request_failed",
                    f"Failed to fetch {url} after {retry_count} attempts: {e}",
                    url,
                )
            time.sleep(2**attempt)

    return None


def clean_text(text: Union[str, Sequence[str], None]) -> Optional[str]:
    """Clean and normalize text content.

    A multi-valued attribute such as rel reaches this as a list of its values,
    so join those back into the one string the rest of the pipeline expects.
    """
    if not text:
        return None
    if not isinstance(text, str):
        text = " ".join(text)
    text = text.strip()
    text_lower = text.lower()

    if text_lower in {"more information...", "click here", "read more"}:
        return None

    if any(
        phrase in text_lower
        for phrase in [
            "javascript is not essential",
            "turn javascript on",
            "interaction with the content will be limited",
        ]
    ):
        return None

    return text


def registrable_name(netloc: str) -> Optional[str]:
    """Reduce a host to the part of it that carries meaning for scoring.

    A leading www and the trailing suffix say nothing about what a page is
    about, so example.com and www.example.co.uk both come back as example.
    Matching on whole labels rather than on substrings keeps the suffix of one
    host from being cut out of the middle of another.
    """
    labels = [label for label in netloc.lower().split(".") if label]
    if not labels:
        return None

    if labels[0] == "www":
        labels = labels[1:]

    while len(labels) > 1 and labels[-1] in PUBLIC_SUFFIX_LABELS:
        labels = labels[:-1]

    return labels[-1] if labels else None


def process_url(url_str: str, processed_domains: Set[str]) -> List[str]:
    """Reduce a URL to the domain and path words that carry meaning.

    A domain already seen on this page contributes nothing the second time, so
    the caller's set keeps it out of every later link's text.
    """
    if not url_str:
        return []

    parsed = urlparse(url_str)
    components = []

    domain = registrable_name(parsed.netloc)
    if domain and domain not in processed_domains:
        components.append(domain)
        processed_domains.add(domain)

    path = parsed.path.strip("/")
    if path:
        components.extend(
            word
            for word in re.split(r"[/-]", path)
            if word and word.lower() not in GENERIC_PATH_WORDS
        )

    return components


def extract_metadata(soup: BeautifulSoup) -> Dict[str, Any]:
    """Extract the page title and description, dropping a stub description."""
    metadata = {}
    if soup.title:
        metadata["title"] = clean_text(soup.title.get_text())

    meta_description = soup.find("meta", attrs={"name": "description"})
    if meta_description and meta_description.get("content"):
        desc = clean_text(meta_description.get("content"))
        if desc and len(desc) > MIN_DESCRIPTION_LENGTH:
            if len(desc) > MAX_DESCRIPTION_LENGTH:
                desc = desc[:MAX_DESCRIPTION_LENGTH] + "..."
            metadata["description"] = desc
    return metadata


def extract_context(link: Tag) -> Dict[str, Any]:
    """Extract and clean surrounding context for a link."""
    context: Dict[str, Any] = {}
    try:
        prev_elem = link.find_previous(CONTEXT_TAGS)
        if prev_elem:
            context["previous_text"] = clean_text(prev_elem.get_text())

        next_elem = link.find_next(CONTEXT_TAGS)
        if next_elem:
            context["next_text"] = clean_text(next_elem.get_text())

        headings = [h.get_text(strip=True) for h in link.find_parents(HEADING_TAGS)]
        if headings:
            context["heading_hierarchy"] = headings
    except Exception as e:
        logger.warning("Error extracting context: %s", e)
    return context


def process_link_attributes(link: Tag) -> Dict[str, Any]:
    """Process and clean link attributes."""
    href = link.get("href")
    text = clean_text(link.get_text())
    title = clean_text(link.get("title"))
    aria_label = clean_text(link.get("aria-label"))

    rel = clean_text(link.get("rel"))
    if rel and rel.lower() in UNINFORMATIVE_REL:
        rel = None

    return {
        "href": href,
        "text": text,
        "title": title,
        "aria_label": aria_label,
        "rel": rel,
    }


def collect_text_components(
    link_attrs: Dict[str, Any],
    metadata: Dict[str, Any],
    context: Dict[str, Any],
    url_components: List[str],
) -> List[str]:
    """Combine everything describing a link into one deduplicated list."""
    text_parts = [
        link_attrs["text"],
        link_attrs["title"],
        link_attrs["aria_label"],
        link_attrs["rel"],
        metadata.get("title"),
        metadata.get("description"),
        *url_components,
        context.get("previous_text"),
        context.get("next_text"),
        *context.get("heading_hierarchy", []),
    ]

    return list(dict.fromkeys(part for part in text_parts if part))


def create_link_data(
    link_attrs: Dict[str, Any],
    keyword: str,
    context: Dict[str, Any],
    metadata: Dict[str, Any],
    source_url: str,
    processed_text: str,
) -> Dict[str, Any]:
    """Create the final link data dictionary."""
    return {
        "href": link_attrs["href"],
        "keyword": keyword,
        "text": link_attrs["text"],
        "title": link_attrs["title"],
        "aria-label": link_attrs["aria_label"],
        "rel": link_attrs["rel"],
        "context": context,
        "metadata": metadata,
        "source_url": source_url,
        "processed_text": processed_text,
    }


def parse_content(html: str, target_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse HTML content to extract links and context."""
    results: List[Dict[str, Any]] = []

    if not html or not isinstance(html, str):
        logger.error("Invalid HTML content received")
        return results

    try:
        soup = BeautifulSoup(html, "html.parser")
        if not soup.find():
            logger.error("No parseable content found in HTML")
            return results

        metadata = extract_metadata(soup)
        container_selector = target_config.get("container_selector", "body")
        containers = soup.select(container_selector) if container_selector else [soup]

        processed_domains: Set[str] = set()
        keyword = target_config.get("keyword", "")

        for container in containers:
            links = container.find_all("a")
            logger.info("Found %d links in container", len(links))

            for link in links:
                try:
                    link_attrs = process_link_attributes(link)
                    if not link_attrs["href"]:
                        continue

                    context = extract_context(link)
                    url_components = process_url(link_attrs["href"], processed_domains)
                    text_components = collect_text_components(
                        link_attrs, metadata, context, url_components
                    )

                    link_data = create_link_data(
                        link_attrs=link_attrs,
                        keyword=keyword,
                        context=context,
                        metadata=metadata,
                        source_url=target_config["url"],
                        processed_text=" ".join(text_components),
                    )

                    results.append(link_data)

                except Exception as e:
                    logger.error("Error processing link: %s", str(e), exc_info=True)
                    continue

        logger.info("Successfully parsed %d links", len(results))
        return results

    except Exception as e:
        logger.error("Error parsing content: %s", str(e))
        return results


def scrape_target(
    target_config: Dict[str, Any],
    headers: Dict[str, str],
    timeout: int,
    retry_count: int,
) -> Dict[str, Any]:
    """Scrape a single target URL."""

    try:
        url = target_config.get("url")
        if not url:
            logger.error("No URL specified in target config")
            return format_error("missing_url", "No URL specified in target config")

        try:
            url = assert_fetchable(url)
        except UrlNotAllowed as error:
            logger.warning("Refusing to fetch %s: %s", url, error)
            return format_error("url_not_allowed", str(error), url)
        target_config["url"] = url

        logger.info("Fetching content from %s", url)
        response = fetch_with_requests(url, headers, timeout, retry_count)

        if not response:
            logger.error("Failed to fetch content from %s", url)
            return format_error("fetch_failed", f"Failed to fetch content from {url}")

        if "error" in response:
            return response

        results = parse_content(response["content"], target_config)
        logger.info("Found %d items from %s", len(results), url)
        return {"results": results}

    except Exception as e:
        logger.error("Error scraping target %s: %s", url, str(e), exc_info=True)
        return format_error("scraping_error", str(e), url)


def scrape(config: Dict[str, Any]) -> Dict[str, Any]:
    """Scrape the first target in the config, which is the only one a job has."""
    targets = config.get("targets", [])
    if not targets:
        logger.error("No targets specified in config")
        return format_error("missing_targets", "No targets specified in config")

    logger.info("Processing target: %s", targets[0].get("url"))
    return scrape_target(
        targets[0], {"User-Agent": USER_AGENT}, DEFAULT_TIMEOUT, DEFAULT_RETRY_COUNT
    )
