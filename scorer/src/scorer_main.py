"""
Main entry point for the scorer processor.
"""

import os
import sys
from flask import Flask, jsonify
from scorer_processor import ScorerProcessor

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
from util.queue_util import QueueManager
from util.error_util import format_error
from util.health_util import perform_health_check

app = Flask(__name__)

processor = ScorerProcessor()


@app.route("/health", methods=["GET"])
def health_check():
    """Report whether this service can reach the queue."""
    return perform_health_check("scorer_processor")


@app.route("/process", methods=["POST"])
def process_endpoint():
    """API endpoint to trigger queue processing."""
    queue_util = QueueManager(QueueManager.get_redis_config(wait_time=10))
    try:
        return jsonify({"message": queue_util.process_queue(processor.process_item)})
    except Exception as e:
        return jsonify(format_error("scorer_processor_error", str(e))), 500
    finally:
        queue_util.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
