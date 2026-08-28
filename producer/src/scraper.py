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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


MAX_REDIRECTS = 5
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
    """Fetch URL content using requests library with rate limiting."""
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
                "Warning: Attempt %d/%d failed for %s: %s",
                attempt + 1,
                retry_count,
                url,
                str(e),
            )
            if attempt < retry_count - 1:
                time.sleep(2**attempt)  # Exponential backoff
            elif attempt == retry_count - 1:
                return {
                    "error": "request_failed",
                    "message": f"Failed to fetch {url} after {retry_count} attempts: {str(e)}",
                    "url": url,
                }

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

    # Filter out common unwanted messages
    if text.lower() in {"more information...", "click here", "read more"}:
        return None

    # Filter JavaScript warning messages with flexible matching
    text_lower = text.lower()
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


def process_url(url_str: str, processed_domains: Set[str]) -> List[str]:
    """Process a URL and return meaningful components."""
    if not url_str:
        return []

    parsed = urlparse(url_str)
    components = []

    # Process domain
    if parsed.netloc:
        domain = parsed.netloc.lower()
        # Remove common prefixes and suffixes
        domain = domain.replace("www.", "").replace(".com", "").replace(".org", "")
        if domain and domain not in processed_domains:
            components.append(domain)
            processed_domains.add(domain)

    # Process path
    if parsed.path:
        path = parsed.path.strip("/")
        if path:
            # Split path into meaningful words, handling both slashes and hyphens
            path_words = [word for word in re.split(r"[/-]", path) if word]
            # Filter out common generic terms
            path_words = [
                word
                for word in path_words
                if word.lower() not in {"index", "home", "page", "default"}
            ]
            components.extend(path_words)

    return components


def extract_metadata(soup: BeautifulSoup) -> Dict[str, Any]:
    """Extract and clean metadata from the page."""
    metadata = {}
    if soup.title:
        metadata["title"] = clean_text(soup.title.get_text())

    meta_description = soup.find("meta", attrs={"name": "description"})
    if meta_description and meta_description.get("content"):
        desc = clean_text(meta_description.get("content"))
        if desc and len(desc) > 10:  # Only add if it's not too short
            if len(desc) > 300:  # Truncate very long descriptions
                desc = desc[:300] + "..."
            metadata["description"] = desc
    return metadata


def extract_context(link: Tag) -> Dict[str, Any]:
    """Extract and clean surrounding context for a link."""
    context: Dict[str, Any] = {}
    try:
        # Get previous text
        prev_elem = link.find_previous(["p", "h1", "h2", "h3", "li"])
        if prev_elem:
            context["previous_text"] = clean_text(prev_elem.get_text())

        # Get next text
        next_elem = link.find_next(["p", "h1", "h2", "h3", "li"])
        if next_elem:
            context["next_text"] = clean_text(next_elem.get_text())

        # Get heading hierarchy
        headings = [
            h.get_text(strip=True) for h in link.find_parents(["h1", "h2", "h3"])
        ]
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

    # Process rel attribute
    rel = clean_text(link.get("rel"))
    if rel and rel.lower() in ["nofollow", "noopener"]:
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
    """Collect and combine all text components for a link."""
    text_parts = []

    # Add link attributes
    if link_attrs["text"]:
        text_parts.append(link_attrs["text"])
    if link_attrs["title"]:
        text_parts.append(link_attrs["title"])
    if link_attrs["aria_label"]:
        text_parts.append(link_attrs["aria_label"])
    if link_attrs["rel"]:
        text_parts.append(link_attrs["rel"])

    # Add metadata
    if metadata.get("title"):
        text_parts.append(metadata["title"])
    if metadata.get("description"):
        text_parts.append(metadata["description"])

    # Add URL components
    text_parts.extend(url_components)

    # Add context
    if context.get("previous_text"):
        text_parts.append(context["previous_text"])
    if context.get("next_text"):
        text_parts.append(context["next_text"])
    if context.get("heading_hierarchy"):
        text_parts.extend(context["heading_hierarchy"])

    # Remove duplicates while preserving order
    return list(dict.fromkeys(text_parts))


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
        if not soup.find():  # Check if parsed content is empty
            logger.error("No parseable content found in HTML")
            return results

        metadata = extract_metadata(soup)
        container_selector = target_config.get("container_selector", "body")
        containers = soup.select(container_selector) if container_selector else [soup]

        processed_domains: Set[str] = set()
        keyword = target_config.get("keyword", "")

        for container in containers:
            # Find all links in the container
            links = container.find_all("a")
            logger.info("Found %d links in container", len(links))

            for link in links:
                try:
                    # Process link attributes
                    link_attrs = process_link_attributes(link)
                    if not link_attrs["href"]:
                        continue

                    # Extract context
                    context = extract_context(link)

                    # Process URL components
                    url_components = process_url(link_attrs["href"], processed_domains)

                    # Collect text components
                    text_components = collect_text_components(
                        link_attrs, metadata, context, url_components
                    )

                    # Create link data
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

        # If there was an error during fetching (like robots.txt disallowed)
        if "error" in response:
            return response

        # Anything that is not an error carries content to parse.
        results = parse_content(response["content"], target_config)
        logger.info("Found %d items from %s", len(results), url)
        return {"results": results}

    except Exception as e:
        logger.error("Error scraping target %s: %s", url, str(e), exc_info=True)
        return format_error("scraping_error", str(e), url)


def scrape(config: Dict[str, Any]) -> Dict[str, Any]:
    """Main scraping function that processes all targets in the config."""
    headers = {"User-Agent": USER_AGENT}
    timeout = 30
    retry_count = 3

    try:
        targets = config.get("targets", [])
        if not targets:
            logger.error("No targets specified in config")
            return format_error("missing_targets", "No targets specified in config")

        # Since we're only processing one target at a time in practice,
        # we can return the error response directly
        target = targets[0]
        logger.info("Processing target: %s", target.get("url"))
        target_result = scrape_target(target, headers, timeout, retry_count)

        # If there's an error, propagate it up
        if isinstance(target_result, dict) and "error" in target_result:
            return target_result

        # If we have results, return them
        if "results" in target_result:
            return target_result

        return format_error("unknown_error", "Unknown error occurred during scraping")

    except Exception as e:
        logger.error("Error in main scrape function: %s", str(e), exc_info=True)
        return format_error("scraping_error", str(e))
