"""
Main entry point for the database processor.
Takes processed items from Redis queue and stores them in SQL database.
"""

import os
import sys
from flask import Flask, request, jsonify
from db_processor import DatabaseProcessor, ScrapedItem

# Add root directory to path for importing queue_util
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
from util.queue_util import QueueManager
from util.health_util import perform_health_check
from util.error_util import format_error

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health_check():
    return perform_health_check("db_processor")


@app.route("/process", methods=["POST"])
def process_endpoint():
    """API endpoint to trigger queue processing."""
    try:
        # Initialize Redis connection with processed queue
        queue_util = QueueManager(
            QueueManager.get_redis_config(queue_name="scraped_items_processed")
        )

        # Initialize database processor
        db_processor = DatabaseProcessor()
        # Process items from the queue
        items = queue_util.process_queue(
            lambda item: db_processor.process_item(item)
        )

        queue_util.clear_queues()

        return jsonify({"message": items})
    except Exception as e:
        return (
            jsonify(
                format_error(str(e), "Error storing data in database")
            ),
            500,
        )


@app.route("/query", methods=["GET"])
def query_items():
    """Query items by keyword and source URL."""
    try:
        # Get query parameters
        keyword = request.args.get("keyword")
        source_url = request.args.get("source_url")

        # Initialize database session
        db_processor = DatabaseProcessor()
        session = db_processor.session()

        try:
            # Build query
            query = session.query(ScrapedItem)
            if keyword:
                query = query.filter(ScrapedItem.keyword == keyword)
            if source_url:
                query = query.filter(ScrapedItem.source_url == source_url)

            # Sort by relevance score in descending order
            query = query.order_by(ScrapedItem.relevance_score.desc())

            # Execute query and get results
            results = query.all()

            # Convert results to list of dictionaries
            items = [
                {
                    "id": item.id,
                    "keyword": item.keyword,
                    "source_url": item.source_url,
                    "href_url": item.href_url,
                    "relevance_score": item.relevance_score,
                    "raw_data": item.raw_data,
                }
                for item in results
            ]

            return jsonify({"items": items, "count": len(items)})

        finally:
            session.close()

    except Exception as e:
        return format_error("db_query_error", str(e))


@app.route("/query/href", methods=["GET"])
def query_by_href():
    """Query item details by href URL."""
    try:
        # Get href URL from query parameters
        href_url = request.args.get("href_url")

        if not href_url:
            return jsonify(format_error("href_url parameter is required")), 400

        # Initialize database session
        db_processor = DatabaseProcessor()
        session = db_processor.session()

        try:
            # Query for the item with matching href_url
            item = (
                session.query(ScrapedItem)
                .filter(ScrapedItem.href_url == href_url)
                .first()
            )

            if not item:
                return (
                    jsonify(format_error("No item found with the specified href URL")),
                    404,
                )

            # Return the relevant information
            result = {
                "href_url": item.href_url,
                "source_url": item.source_url,
                "keyword": item.keyword,
                "relevance_score": item.relevance_score,
            }

            return jsonify(result)

        finally:
            session.close()

    except Exception as e:
        return format_error("db_query_error", str(e))


def main() -> None:
    """Initialize and run the database processor."""
    # Check if we're running in API mode (no arguments)
    if len(sys.argv) == 1:
        # Run as API server
        app.run(host="0.0.0.0", port=5000)
    else:
        # Run as command line tool
        process_endpoint()


if __name__ == "__main__":
    main()
