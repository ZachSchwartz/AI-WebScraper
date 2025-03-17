"""
Web scraper module for collecting data from target websites.
"""

import time
import random
import re
from typing import Dict, List, Any, Optional, Set
from urllib.robotparser import RobotFileParser
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup


def is_allowed_by_robots(url: str, user_agent: str) -> bool:
    """Check if the URL is allowed by robots.txt."""
    try:
        rp = RobotFileParser()
        rp.set_url(url.rstrip("/") + "/robots.txt")
        rp.read()
        return rp.can_fetch(user_agent, url)
    except Exception as e:
        print(f"Warning: Error checking robots.txt for {url}: {str(e)}")
        return True


def fetch_with_requests(
    url: str, headers: Dict[str, str], timeout: int, retry_count: int
) -> Optional[str]:
    """Fetch URL content using requests library with rate limiting."""
    if not is_allowed_by_robots(url, headers["User-Agent"]):
        print(f"Info: Skipping {url} (disallowed by robots.txt)")
        return None

    for attempt in range(retry_count):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            print(
                f"Warning: Attempt {attempt + 1}/{retry_count} failed for {url}: {str(e)}"
            )
            if attempt < retry_count - 1:
                time.sleep(2**attempt)  # Exponential backoff

    print(f"Error: Failed to fetch {url} after {retry_count} attempts")
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
        print(f"Warning: Error extracting metadata: {str(e)}")
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
        print(f"Warning: Error extracting context: {str(e)}")
    return context


def process_link_attributes(link: BeautifulSoup) -> Dict[str, Any]:
    """Process and clean link attributes."""
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
        "scraped_at": int(time.time()),
        "processed_text": processed_text,
    }


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
                # Process link attributes
                link_attrs = process_link_attributes(link)

                # Extract context
                context = extract_context(link)

                # Process URLs
                url_components = []
                if link_attrs["href"]:
                    url_components.extend(
                        process_url(link_attrs["href"], processed_domains)
                    )
                if target_config.get("url"):
                    url_components.extend(
                        process_url(target_config["url"], processed_domains)
                    )

                # Collect all text components
                text_parts = collect_text_components(
                    link_attrs, metadata, context, url_components
                )

                # Create final link data
                link_data = create_link_data(
                    link_attrs,
                    keyword,
                    context,
                    metadata,
                    target_config.get("url", ""),
                    " ".join(text_parts),
                )
                results.append(link_data)

    except Exception as e:
        print(f"Error: Error parsing content: {str(e)}")
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
        print("Error: Target missing URL")
        return []

    print(f"Info: Scraping target: {url}")

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
                print(
                    f"Info: Scraped {len(results)} items from {target_config.get('url')}"
                )
                all_results.extend(results)
            else:
                print(f"Warning: No results from {target_config.get('url')}")
    except Exception as e:
        print(f"Error: Error during scraping: {str(e)}")
    return all_results
