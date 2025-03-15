"""
Web scraper module for collecting data from target websites.
"""

import time
import random
import logging
from typing import Dict, List, Any, Optional
from urllib.robotparser import RobotFileParser
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


def extract_metadata(soup: BeautifulSoup) -> Dict[str, Any]:
    """Extract metadata from the page."""
    metadata = {}
    try:
        metadata["title"] = soup.title.get_text(strip=True) if soup.title else None
        meta_description = soup.find("meta", attrs={"name": "description"})
        metadata["description"] = (
            meta_description.get("content") if meta_description else None
        )
    except Exception as e:
        logger.warning("Error extracting metadata: %s", str(e))
    return metadata


def parse_content(html: str, target_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse HTML content to extract links and context."""
    results = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        metadata = extract_metadata(soup)
        container_selector = target_config.get("container_selector", "body")
        containers = soup.select(container_selector) if container_selector else [soup]

        for container in containers:
            for link in container.find_all("a"):
                link_data = {
                    "href": link.get("href"),
                    "text": link.get_text(strip=True),
                    "title": link.get("title"),
                    "aria-label": link.get("aria-label"),
                    "rel": link.get("rel"),
                    "context": {
                        "previous_text": (
                            link.find_previous(["p", "h1", "h2", "h3", "li"]).get_text(
                                strip=True
                            )
                            if link.find_previous(["p", "h1", "h2", "h3", "li"])
                            else None
                        ),
                        "next_text": (
                            link.find_next(["p", "h1", "h2", "h3", "li"]).get_text(
                                strip=True
                            )
                            if link.find_next(["p", "h1", "h2", "h3", "li"])
                            else None
                        ),
                        "heading_hierarchy": [
                            h.get_text(strip=True)
                            for h in link.find_parents(["h1", "h2", "h3"])
                        ],
                    },
                    "metadata": metadata,
                    "source_url": target_config.get("url", ""),
                    "scraped_at": int(time.time()),
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
