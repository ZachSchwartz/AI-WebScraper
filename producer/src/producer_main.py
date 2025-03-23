"""
Main entry point for the web scraper producer.
"""

import os
import sys
import logging
import json
from typing import Dict, Any
from flask import Flask, request, jsonify
from scraper import scrape


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
from queue_manager import QueueManager
from health_util import perform_health_check
from error_util import format_error

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health_check():
    return perform_health_check("producer")


SCRAPER_CONFIG = {
    "targets": [
        {
            "url": "",
            "keyword": "",
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


def run_scraper(
    queue_manager: QueueManager, target_url: str, target_keyword: str
) -> Dict[str, Any]:
    """Run the scraper and publish results to the queue."""
    print("Starting scraping job")

    SCRAPER_CONFIG["targets"][0]["url"] = target_url
    SCRAPER_CONFIG["targets"][0]["keyword"] = target_keyword
    result = scrape(SCRAPER_CONFIG)

    # Check if we got an error response
    if isinstance(result, dict):
        if "error" in result:
            return format_error("scraping_failed", "Please check if url is spelled correctly, or website may not allow scraping")

        results = result["results"]
        if results:
            print(f"Scraped {len(results)} items")

            # Publish results to the queue
            for item in results:
                queue_manager.publish_item(item)

            print(f"Published {len(results)} items to queue")

            queue_name = "scraped_items"
            item_json = queue_manager.redis_client.rpop(queue_name)

            if item_json:
                first_item = json.loads(item_json)
                # Push the item back to the front of the queue since we want to keep it
                queue_manager.redis_client.lpush(queue_name, item_json)
                queue_manager.close()
                return first_item


@app.route("/scrape", methods=["POST"])
def scrape_endpoint():
    """API endpoint to handle scraping requests."""
    logger.info("Received scrape request")
    data = request.json
    logger.info("Request data: %s", data)

    url = data.get("url")
    keyword = data.get("keyword")

    logger.info("Initializing queue manager")
    queue_config = QueueManager.get_redis_config()
    logger.info("Queue config: %s", queue_config)
    queue_manager = QueueManager(queue_config)

    logger.info("Starting scraper")
    result = run_scraper(queue_manager, url, keyword)

    # Check if we got an error response
    if isinstance(result, dict) and "error" in result:
        return jsonify(result), 400

    # If we have a valid result, return it
    if result:
        return jsonify(result)


def main(target_url: str, target_keyword: str) -> None:
    """Main entry point for the scraper when run directly."""
    queue_manager = QueueManager(QueueManager.get_redis_config())
    print("Queue manager initialized")

    try:
        print(f"Scraping URL: {target_url} with keyword: {target_keyword} in main")
        first_item = run_scraper(queue_manager, target_url, target_keyword)
        if first_item:
            print("First item from queue:")
            print(json.dumps(first_item, indent=2))
    finally:
        queue_manager.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
