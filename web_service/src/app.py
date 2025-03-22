"""
Web service module that provides a Flask-based API for web scraping and data processing.
This service coordinates between producer, LLM, and database services to scrape, analyze,
and store web content based on user queries.
"""

import os
import logging
import requests
from flask import Flask, render_template, request, jsonify

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

PRODUCER_SERVICE_URL = os.getenv("PRODUCER_SERVICE_URL", "http://producer:5000")
LLM_SERVICE_URL = os.getenv("LLM_SERVICE_URL", "http://llm:5000")
DB_SERVICE_URL = os.getenv("DB_SERVICE_URL", "http://db_processor:5000")


def create_error_response(error: Exception, status_code: int = 500):
    """Create a standardized error response"""
    logger.error("%s: %s", error.__class__.__name__, str(error))
    return jsonify({"error": str(error), "status": "error"}), status_code


def make_service_request(
    service_url: str, endpoint: str, method: str = "POST", **kwargs
):
    """Make a standardized request to a service"""
    try:
        url = f"{service_url}/{endpoint.lstrip('/')}"
        response = requests.request(method, url, timeout=10, **kwargs)
        response.raise_for_status()
        data = response.json()
        logger.info("Service response from %s: %s", url, data)
        return data
    except requests.exceptions.RequestException as e:
        return create_error_response(e)


def get_response(service_url: str, url: str = None, keyword: str = None):
    """Get response from a service."""
    if url is not None and keyword is not None:
        return make_service_request(
            service_url, "scrape", json={"url": url, "keyword": keyword}
        )
    return make_service_request(service_url, "process")


@app.route("/")
def index():
    """Render the main application interface.
    
    Returns:
        str: Rendered HTML template for the index page.
    """
    return render_template("index.html")


@app.route("/api/scrape", methods=["POST"])
def scrape():
    """Process a web scraping request by coordinating with multiple services.
    
    The function orchestrates the following steps:
    1. Sends URL and keyword to producer service for scraping
    2. Triggers LLM service for content analysis
    3. Retrieves processed results from database service
    4. Sorts and returns relevant links based on relevance scores
    
    Returns:
        tuple: JSON response containing scraped results and HTTP status code
    """
    logger.info("Received scrape request")
    try:
        data = request.json
        url = data.get("url")
        keyword = data.get("keyword")

        get_response(PRODUCER_SERVICE_URL, url, keyword)
        get_response(LLM_SERVICE_URL)
        db_data = get_response(DB_SERVICE_URL)

        links = []
        if isinstance(db_data.get("message"), list):
            for item in db_data["message"]:
                if isinstance(item, dict) and "relevance_analysis" in item:
                    analysis = item["relevance_analysis"]
                    links.append(
                        {
                            "url": analysis.get("href_url", ""),
                            "score": analysis.get("score", 0),
                        }
                    )

        # Sort links by score in descending order
        links.sort(key=lambda x: float(x["score"] or 0), reverse=True)

        return jsonify(
            {
                "source_url": url,
                "keyword": keyword,
                "results": links,
                "count": len(links),
            }
        )
    except Exception as e:
        return create_error_response(e)


@app.route("/db/query")
def db_query():
    """Proxy database queries to the DB service.
    
    Acts as a proxy endpoint that forwards query parameters to the database service
    and returns the results. Handles connection errors and service availability issues
    with appropriate status codes.
    
    Returns:
        tuple: JSON response from database service and HTTP status code
    """
    try:
        return make_service_request(
            DB_SERVICE_URL, "query", method="GET", params=request.args
        )
    except Exception as e:
        return create_error_response(
            e, 503 if isinstance(e, requests.exceptions.RequestException) else 500
        )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
