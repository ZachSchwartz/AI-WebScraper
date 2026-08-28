"""
Main entry point for the web scraper producer.
"""

import copy
import logging
from typing import Any, Dict, Optional
from flask import Flask, request, jsonify
from scraper import scrape

from util.queue_util import QueueManager
from util.health_util import perform_health_check
from util.error_util import format_error

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health_check():
    """Report whether this service can reach the queue."""
    return perform_health_check("producer", QueueManager.check_connection)


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
    queue_util: QueueManager,
    target_url: str,
    target_keyword: str,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Scrape one target and publish every link it found to the queue.

    Returns:
        A summary of what was published, or a formatted error. A page with no
        links publishes nothing and is reported as a count of zero rather than
        as a failure.
    """
    logger.info("Starting scraping job %s for %s", job_id, target_url)

    # The config is module level and Flask serves requests concurrently, so each
    # job fills in a copy rather than overwriting the shared template.
    config = copy.deepcopy(SCRAPER_CONFIG)
    config["targets"][0]["url"] = target_url
    config["targets"][0]["keyword"] = target_keyword

    result = scrape(config)
    if "error" in result:
        logger.warning("Scrape of %s failed: %s", target_url, result.get("message"))
        return result

    results = result.get("results", [])
    published = sum(1 for item in results if _publish(queue_util, item, job_id))
    logger.info("Published %d of %d items to the queue", published, len(results))

    return {"job_id": job_id, "url": target_url, "published": published}


def _publish(
    queue_util: QueueManager, item: Dict[str, Any], job_id: Optional[str]
) -> bool:
    """Tag an item with its job and hand it to the queue."""
    item["job_id"] = job_id
    return queue_util.publish_item(item)


@app.route("/scrape", methods=["POST"])
def scrape_endpoint():
    """API endpoint to handle scraping requests."""
    data = request.get_json(silent=True) or {}
    url = data.get("url")
    keyword = data.get("keyword")

    if not url or not keyword:
        return (
            jsonify(
                format_error("missing_parameter", "Both url and keyword are required")
            ),
            400,
        )

    job_id = data.get("job_id")
    queue_util = QueueManager(QueueManager.get_redis_config(job_id=job_id))
    try:
        result = run_scraper(queue_util, url, keyword, job_id)
    finally:
        queue_util.close()

    if "error" in result:
        return jsonify(result), 400

    return jsonify(result)


def main(target_url: str, target_keyword: str) -> None:
    """Main entry point for the scraper when run directly."""
    queue_util = QueueManager(QueueManager.get_redis_config())
    try:
        logger.info("Scraping %s for %s", target_url, target_keyword)
        logger.info("Result: %s", run_scraper(queue_util, target_url, target_keyword))
    finally:
        queue_util.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
