"""
Main entry point for the LLM processor.
"""

import os
import sys
from flask import Flask, jsonify
from llm_processor import LLMProcessor

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
from util.queue_util import QueueManager
from util.error_util import format_error
from util.health_util import perform_health_check

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health_check():
    return perform_health_check("llm_processor")


@app.route("/process", methods=["POST"])
def process_endpoint():
    """API endpoint to trigger queue processing."""
    try:
        # Initialize Redis connection with longer wait time for LLM processing
        queue_util = QueueManager(QueueManager.get_redis_config(wait_time=10))

        # Process items
        processor = LLMProcessor()
        processed_items = queue_util.process_queue(
            lambda item: processor.process_item(item)
        )

        return jsonify({"message": processed_items})
    except Exception as e:
        return format_error("llm_processor_error", str(e))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
