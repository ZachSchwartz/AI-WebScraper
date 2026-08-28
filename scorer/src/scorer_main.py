"""
Main entry point for the scorer processor.
"""

from flask import Flask, jsonify, request
from scorer_processor import ScorerProcessor

from util.queue_util import QueueManager
from util.error_util import format_error
from util.health_util import perform_health_check

app = Flask(__name__)

processor = ScorerProcessor()


@app.route("/health", methods=["GET"])
def health_check():
    """Report whether this service can reach the queue."""
    return perform_health_check("scorer_processor", QueueManager.check_connection)


@app.route("/process", methods=["POST"])
def process_endpoint():
    """API endpoint to trigger queue processing."""
    job_id = (request.get_json(silent=True) or {}).get("job_id")
    queue_util = QueueManager(
        QueueManager.get_redis_config(wait_time=10, job_id=job_id)
    )
    try:
        return jsonify({"message": queue_util.process_queue(processor.process_item)})
    except Exception as e:
        return jsonify(format_error("scorer_processor_error", str(e))), 500
    finally:
        queue_util.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
