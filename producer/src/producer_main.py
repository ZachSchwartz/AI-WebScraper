"""
Main entry point for the web scraper producer.
"""

import argparse
import os
import sys
from typing import Optional
import requests
from scraper import scrape
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
from queue_manager import QueueManager



def run_scraper(
    queue_manager: QueueManager, target_url: str, target_keyword: str
) -> None:
    """Run the scraper and publish results to the queue."""
    try:
        print("Starting scraping job")
        scraper_config = {
            "targets": [
                {
                    "url": target_url,
                    "keyword": target_keyword,
                    "container_selector": "body",  # Or a more specific container
                    "fields": {
                        "links": {
                            "selector": "a",  # Target all <a> tags
                            "extract": [
                                "href",
                                "text",
                                "title",
                                "aria-label",
                                "rel",
                            ],  # Extract link attributes
                        },
                        "context": {
                            "selector": "p, h1, h2, h3, li",  # Extract surrounding text
                            "extract": "text",
                        },
                        "metadata": {
                            "selector": "meta",  # Extract meta tags (e.g., description, keywords)
                            "extract": ["name", "content"],
                        },
                    },
                }
            ]
        }

        # Call the standalone scrape function
        results = scrape(scraper_config)
        if results:
            print(f"Scraped {len(results)} items")

            # Publish results to the queue
            for item in results:
                queue_manager.publish_item(item)

            print(f"Published {len(results)} items to queue")
        else:
            print("No results found during scraping")

    except (requests.exceptions.RequestException, ValueError) as e:
        print(f"Error in scraping job: {str(e)}")
    except Exception as e:
        print(f"Unexpected error in scraping job: {str(e)}")
        raise  # Re-raise unexpected exceptions


def main(target_url: str, target_keyword: str) -> None:
    """Main entry point for the scraper."""
    queue_config = {
        "type": "redis",
        "host": "redis",  # Docker service name
        "port": 6379,
        "queue_name": "scraped_items",
    }

    queue_manager = QueueManager(queue_config)
    print("Queue manager initialized")

    try:
        # Clear queues before starting
        queue_manager.clear_queues()
        print(f"Scraping URL: {target_url} with keyword: {target_keyword} in main")
        run_scraper(queue_manager, target_url, target_keyword)
    finally:
        queue_manager.read_queue()
        queue_manager.close()


if __name__ == "__main__":
    # Try to get URL and keyword from environment variables first
    url: Optional[str] = os.environ.get("URL")
    keyword: Optional[str] = os.environ.get("KEYWORD")

    # If not in environment, try command line arguments
    if not url or not keyword:
        parser = argparse.ArgumentParser(description="Web scraper producer")
        parser.add_argument("--url", required=True, help="Target URL to scrape")
        parser.add_argument("--keyword", required=True, help="Keyword to search for")
        args = parser.parse_args()
        url = args.url
        keyword = args.keyword

    if not url or not keyword:
        print("Error: URL and keyword are required")
        sys.exit(1)

    print(f"Scraping URL: {url} with keyword: {keyword}")
    main(url, keyword)
