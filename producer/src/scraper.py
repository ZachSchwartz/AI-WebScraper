"""
Web scraper module for collecting data from target websites.
"""

import time
import random
import logging
import re
from typing import Dict, List, Any, Optional, Set
from urllib.robotparser import RobotFileParser
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def is_allowed_by_robots(url: str, user_agent: str) -> bool:
    """Check if the URL is allowed by robots.txt."""
    try:
        rp = RobotFileParser()
        rp.set_url(url.rstrip("/") + "/robots.txt")
        rp.read()
        return rp.can_fetch(user_agent, url)
    except Exception as e:
        logger.warning("Error checking robots.txt for %s: %s", url, str(e))
        return True


def fetch_with_requests(
    url: str, headers: Dict[str, str], timeout: int, retry_count: int
) -> Optional[str]:
    """Fetch URL content using requests library with rate limiting."""
    if not is_allowed_by_robots(url, headers["User-Agent"]):
        logger.info("Skipping %s (disallowed by robots.txt)", url)
        return None

    for attempt in range(retry_count):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            logger.warning(
                "Attempt %d/%d failed for %s: %s",
                attempt + 1,
                retry_count,
                url,
                str(e),
            )
            if attempt < retry_count - 1:
                time.sleep(2**attempt)  # Exponential backoff

    logger.error("Failed to fetch %s after %d attempts", url, retry_count)
    return None


def clean_text(text: str) -> Optional[str]:
    """Clean and normalize text content."""
    if not text:
        return None
    text = text.strip()
    if text.lower() in {"more information...", "click here", "read more"}:
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
    try:
        if soup.title:
            metadata["title"] = clean_text(soup.title.get_text())

        meta_description = soup.find("meta", attrs={"name": "description"})
        if meta_description and meta_description.get("content"):
            desc = clean_text(meta_description.get("content"))
            if desc and len(desc) > 10:  # Only add if it's not too short
                if len(desc) > 300:  # Truncate very long descriptions
                    desc = desc[:300] + "..."
                metadata["description"] = desc
    except Exception as e:
        logger.warning("Error extracting metadata: %s", str(e))
    return metadata


def extract_context(link: BeautifulSoup) -> Dict[str, Any]:
    """Extract and clean surrounding context for a link."""
    context = {}
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
        logger.warning("Error extracting context: %s", str(e))
    return context


def parse_content(html: str, target_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse HTML content to extract links and context."""
    results = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        metadata = extract_metadata(soup)
        container_selector = target_config.get("container_selector", "body")
        containers = soup.select(container_selector) if container_selector else [soup]
        keyword = target_config.get("keyword", "")
        processed_domains = set()

        for container in containers:
            for link in container.find_all("a"):
                # Clean and process link attributes
                href = link.get("href")
                text = clean_text(link.get_text())
                title = clean_text(link.get("title"))
                aria_label = clean_text(link.get("aria-label"))

                # Process rel attribute
                rel = link.get("rel")
                if rel:
                    if isinstance(rel, list):
                        rel = " ".join(rel)
                    if rel.lower() in ["nofollow", "noopener"]:
                        rel = None

                # Extract context
                context = extract_context(link)

                # Process URLs
                url_components = []
                if href:
                    url_components.extend(process_url(href, processed_domains))
                if target_config.get("url"):
                    url_components.extend(
                        process_url(target_config["url"], processed_domains)
                    )

                # Combine all text components
                text_parts = []
                if text:
                    text_parts.append(text)
                if title:
                    text_parts.append(title)
                if aria_label:
                    text_parts.append(aria_label)
                if rel:
                    text_parts.append(rel)
                if metadata.get("title"):
                    text_parts.append(metadata["title"])
                if metadata.get("description"):
                    text_parts.append(metadata["description"])
                text_parts.extend(url_components)
                if context.get("previous_text"):
                    text_parts.append(context["previous_text"])
                if context.get("next_text"):
                    text_parts.append(context["next_text"])
                if context.get("heading_hierarchy"):
                    text_parts.extend(context["heading_hierarchy"])

                # Remove duplicates while preserving order
                text_parts = list(dict.fromkeys(text_parts))

                link_data = {
                    "href": href,
                    "keyword": keyword,
                    "text": text,
                    "title": title,
                    "aria-label": aria_label,
                    "rel": rel,
                    "context": context,
                    "metadata": metadata,
                    "source_url": target_config.get("url", ""),
                    "scraped_at": int(time.time()),
                    "processed_text": " ".join(text_parts),  # Add pre-processed text
                }
                results.append(link_data)

    except Exception as e:
        logger.error("Error parsing content: %s", str(e))
    return results


def scrape_target(
    target_config: Dict[str, Any],
    headers: Dict[str, str],
    timeout: int,
    retry_count: int,
) -> List[Dict[str, Any]]:
    """Scrape a single target based on configuration."""
    url = target_config.get("url")
    if not url:
        logger.error("Target missing URL")
        return []

    logger.info("Scraping target: %s", url)

    # Apply rate limiting
    time.sleep(random.uniform(2, 5))

    # Fetch content
    html = fetch_with_requests(url, headers, timeout, retry_count)
    if not html:
        return []

    # Parse content
    return parse_content(html, target_config)


def scrape(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Scrape all configured targets."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    timeout = 30
    retry_count = 3

    all_results = []
    try:
        for target_config in config.get("targets", []):
            results = scrape_target(target_config, headers, timeout, retry_count)
            if results:
                logger.info(
                    "Scraped %d items from %s", len(results), target_config.get("url")
                )
                all_results.extend(results)
            else:
                logger.warning("No results from %s", target_config.get("url"))
    except Exception as e:
        logger.error("Error during scraping: %s", str(e))
    return all_results
