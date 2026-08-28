"""
Main entry point for the database processor.
Takes processed items from Redis queue and stores them in SQL database.
"""

from contextlib import contextmanager
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


@contextmanager
def query_session():
    """A session for one read, closed however the request ends."""
    session = DatabaseProcessor().session()
    try:
        yield session
    finally:
        session.close()


@app.route("/process", methods=["POST"])
def process_endpoint():
    """API endpoint to trigger queue processing."""
    try:
        job_id = (request.get_json(silent=True) or {}).get("job_id")
        queue_util = QueueManager(
            QueueManager.get_redis_config(
                queue_name="scraped_items_processed", job_id=job_id
            )
        )

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
    """Query items by keyword and source URL.

    Stored rows are canonicalized on the way in, so the source URL asked about
    is canonicalized the same way rather than matched character for character.
    """
    try:
        keyword = request.args.get("keyword")
        source_url = normalize_url(request.args.get("source_url"))

        with query_session() as session:
            query = session.query(ScrapedItem)
            if keyword:
                query = query.filter(ScrapedItem.keyword == keyword)
            if source_url:
                query = query.filter(ScrapedItem.source_url == source_url)

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
                for item in query.order_by(ScrapedItem.relevance_score.desc()).all()
            ]

            return jsonify({"items": items, "count": len(items)})

    except Exception as e:
        return jsonify(format_error("db_query_error", str(e))), 500


@app.route("/query/href", methods=["GET"])
def query_by_href():
    """Query item details by href URL."""
    try:
        href_url = normalize_url(request.args.get("href_url"))

        if not href_url:
            return (
                jsonify(
                    format_error("missing_parameter", "href_url parameter is required")
                ),
                400,
            )

        with query_session() as session:
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

            return jsonify(
                {
                    "href_url": item.href_url,
                    "source_url": item.source_url,
                    "keyword": item.keyword,
                    "relevance_score": item.relevance_score,
                }
            )

    except Exception as e:
        return jsonify(format_error("db_query_error", str(e))), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
