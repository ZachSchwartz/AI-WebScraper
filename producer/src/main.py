"""
Main entry point for the web scraper producer.
"""

from scraper import scrape  # Import the standalone scrape function
from queue_manager import QueueManager


def run_scraper(queue_manager):
    """Run the scraper and publish results to the queue."""
    try:
        print("Starting scraping job")
        scraper_config = {
            "targets": [
                {
                    "url": "",
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


def main():
    """Main entry point for the scraper."""

    queue_config = {
        "type": "redis",
        "host": "redis",  # Docker service name
        "port": 6379,
        "queue_name": "scraped_items",
    }

    queue_manager = QueueManager(queue_config)
    print("Queue manager initialized")

    run_scraper(queue_manager)


if __name__ == "__main__":
    main()
