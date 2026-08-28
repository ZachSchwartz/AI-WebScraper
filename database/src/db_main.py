"""
Main entry point for the database processor.
Takes processed items from Redis queue and stores them in SQL database.
"""

from flask import Flask, request, jsonify
from db_processor import DatabaseProcessor, ScrapedItem

from util.queue_util import QueueManager
from util.health_util import perform_health_check
from util.error_util import format_error
from util.url_util import normalize_url

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health_check():
    """Report whether this service can reach the queue."""
    return perform_health_check("db_processor", QueueManager.check_connection)


@app.route("/process", methods=["POST"])
def process_endpoint():
    """API endpoint to trigger queue processing."""
    try:
        job_id = (request.get_json(silent=True) or {}).get("job_id")

        # Initialize Redis connection with this job's processed queue
        queue_util = QueueManager(
            QueueManager.get_redis_config(
                queue_name="scraped_items_processed", job_id=job_id
            )
        )

        # Initialize database processor
        db_processor = DatabaseProcessor()
        try:
            items = queue_util.process_queue(db_processor.process_item, forward=False)
        finally:
            queue_util.close()

        return jsonify({"message": items})
    except Exception as e:
        return (
            jsonify(format_error("db_process_error", str(e))),
            500,
        )


@app.route("/query", methods=["GET"])
def query_items():
    """Query items by keyword and source URL."""
    try:
        # Get query parameters
        keyword = request.args.get("keyword")
        # Stored rows are canonicalized on the way in, so canonicalize the query
        # the same way rather than demanding an exact-character match.
        source_url = normalize_url(request.args.get("source_url"))

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
                    "job_id": item.job_id,
                    "processed_date": item.processed_date.isoformat(),
                    "raw_data": item.raw_data,
                }
                for item in results
            ]

            return jsonify({"items": items, "count": len(items)})

        finally:
            session.close()

    except Exception as e:
        return jsonify(format_error("db_query_error", str(e))), 500


@app.route("/query/href", methods=["GET"])
def query_by_href():
    """Query item details by href URL."""
    try:
        # Get href URL from query parameters
        href_url = normalize_url(request.args.get("href_url"))

        if not href_url:
            return (
                jsonify(
                    format_error("missing_parameter", "href_url parameter is required")
                ),
                400,
            )

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
                    jsonify(
                        format_error(
                            "href_not_found",
                            "No item found with the specified href URL",
                            href_url,
                        )
                    ),
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
        return jsonify(format_error("db_query_error", str(e))), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
