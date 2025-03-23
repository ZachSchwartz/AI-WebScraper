"""
Main entry point for the LLM processor.
"""

import os
import sys
from datetime import datetime
from flask import Flask, jsonify
from llm_processor import LLMProcessor

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
from queue_manager import QueueManager

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    try:
        # Check Redis connection
        redis_client = QueueManager.get_redis_client()
        redis_client.ping()
        redis_client.close()

        return jsonify(
            {
                "status": "healthy",
                "service": "llm",
                "timestamp": datetime.now().isoformat(),
            }
        )
    except Exception as e:
        return jsonify({"status": "unhealthy", "service": "llm", "error": str(e)}), 500


@app.route("/process", methods=["POST"])
def process_endpoint():
    """API endpoint to trigger queue processing."""
    try:
        # Initialize Redis connection with longer wait time for LLM processing
        queue_manager = QueueManager(QueueManager.get_redis_config(wait_time=10))

        # Process items
        processor = LLMProcessor()
        processed_items = queue_manager.process_queue(
            lambda item: processor.process_item(item)
        )

        return jsonify({"message": processed_items})
    except Exception as e:
        return jsonify({"error": str(e), "status": "error"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
