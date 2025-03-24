"""
Health utility functions for the web scraper.
"""

from datetime import datetime
from flask import jsonify
from util.queue_util import QueueManager


def perform_health_check(service_name):
    """
    Perform a health check for a service.
    """
    try:
        # Check Redis connection
        redis_client = QueueManager.get_redis_client()
        redis_client.ping()
        redis_client.close()

        return jsonify(
            {
                "status": "healthy",
                "service": service_name,
                "timestamp": datetime.now().isoformat(),
            }
        )
    except Exception as e:
        return (
            jsonify({"status": "unhealthy", "service": service_name, "error": str(e)}),
            500,
        )