"""
Main entry point for the web scraper producer.
"""

import argparse
from scraper import scrape  # Import the standalone scrape function
from queue_manager import QueueManager
from read_queue import read_queue, display_items


def run_scraper(queue_manager, url, keyword):
    """Run the scraper and publish results to the queue."""
    try:
        print("Starting scraping job")
        scraper_config = {
            "targets": [
                {
                    "url": url,
                    "keyword": keyword,
                    "score": "",
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

        # Read and display the queue contents
        print("\nReading queue contents:")
        items = read_queue()
        if items:
            display_items(items)
        else:
            print("No items found in queue after scraping")

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
        run_scraper(queue_manager, url, keyword)
    finally:
        queue_manager.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Web scraper producer')
    parser.add_argument('--url', required=True, help='Target URL to scrape')
    parser.add_argument('--keyword', required=True, help='Keyword to search for')

    args = parser.parse_args()
    main(args.url, args.keyword)
