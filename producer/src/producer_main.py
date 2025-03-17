"""
Main entry point for the web scraper producer.
"""

import argparse
from scraper import scrape  # Import the standalone scrape function
import sys
import os

# Add the root directory to Python path to find queue_manager
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)

from queue_manager import QueueManager


def run_scraper(queue_manager, url, keyword):
    """Run the scraper and publish results to the queue."""
    try:
        print("Starting scraping job")
        scraper_config = {
            "targets": [
                {
                    "url": url,
                    "keyword": keyword,
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

    except Exception as e:
        print(f"Error in scraping job: {str(e)}")


def main(url, keyword):
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
        print(f"Scraping URL: {url} with keyword: {keyword} in main")
        run_scraper(queue_manager, url, keyword)
    finally:
        queue_manager.read_queue()
        queue_manager.close()


if __name__ == "__main__":
    # Try to get URL and keyword from environment variables first
    url = os.environ.get('URL')
    keyword = os.environ.get('KEYWORD')

    # If not in environment, try command line arguments
    if not url or not keyword:
        parser = argparse.ArgumentParser(description='Web scraper producer')
        parser.add_argument('--url', required=True, help='Target URL to scrape')
        parser.add_argument('--keyword', required=True, help='Keyword to search for')
        args = parser.parse_args()
        url = args.url
        keyword = args.keyword
    print(f"Scraping URL: {url} with keyword: {keyword}")
    main(url, keyword)
