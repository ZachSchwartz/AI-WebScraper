"""
Health utility functions for the web scraper.
"""

from datetime import datetime
from typing import Callable, Optional
from flask import jsonify


def perform_health_check(service_name: str, dependency: Optional[Callable] = None):
    """Report whether a service, and what it cannot serve without, are up.

    The dependency is passed in rather than assumed, so this module stays free
    of what any one service happens to need. The web service holds no queue of
    its own, only the three services that do, so it passes none and answers for
    its own liveness rather than for a Redis it never talks to and whose client
    its image does not even install.
    """
    try:
        if dependency is not None:
            dependency()

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
