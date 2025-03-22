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
    
    # Create a user-friendly error message
    if isinstance(error, requests.exceptions.RequestException):
        message = "Unable to complete the request. Please try again later."
    else:
        message = str(error)
    
    return jsonify({
        "error": "scraping_failed",
        "message": message,
        "status": "error"
    }), status_code


def make_service_request(
    service_url: str, endpoint: str, method: str = "POST", **kwargs
):
    """Make a standardized request to a service"""
    try:
        url = f"{service_url}/{endpoint.lstrip('/')}"
        response = requests.request(method, url, timeout=10, **kwargs)
        
        # Get the response data even if status code is not 200
        try:
            data = response.json()
        except ValueError:
            data = {"error": "invalid_response", "message": "Invalid response from service"}
            
        logger.info("Service response from %s: %s", url, data)
        
        # If it's an error response, return it immediately
        if not response.ok or (isinstance(data, dict) and "error" in data):
            return data, response.status_code
            
        return data
        
    except requests.exceptions.RequestException as e:
        logger.error("Request error: %s", str(e))
        return {
            "error": "service_error",
            "message": "Unable to complete the request. Please try again later."
        }, 500


def get_response(service_url: str, url: str = None, keyword: str = None):
    """Get response from a service."""
    try:
        if url is not None and keyword is not None:
            response = make_service_request(
                service_url, "scrape", json={"url": url, "keyword": keyword}
            )
        else:
            response = make_service_request(service_url, "process")
            
        # If response is a tuple (indicating an error response), return it directly
        if isinstance(response, tuple):
            return response[0]  # Return just the JSON part
        return response
        
    except Exception as e:
        logger.error("Error in get_response: %s", str(e))
        return {
            "error": "service_error",
            "message": "Unable to process the request. Please try again later.",
            "status": "error"
        }


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
        
        if not url or not keyword:
            return jsonify({
                "error": "invalid_input",
                "message": "Both URL and keyword are required",
                "status": "error"
            }), 400

        # Call the producer service
        producer_response = make_service_request(
            PRODUCER_SERVICE_URL, 
            "scrape", 
            json={"url": url, "keyword": keyword}
        )
        
        # If producer_response is a tuple, it contains an error
        if isinstance(producer_response, tuple):
            error_data, status_code = producer_response
            return jsonify(error_data), status_code
            
        # If producer response has an error, return it
        if isinstance(producer_response, dict) and "error" in producer_response:
            return jsonify(producer_response), 400

        # Only proceed with LLM and DB if producer was successful
        llm_response = make_service_request(LLM_SERVICE_URL, "process")
        if isinstance(llm_response, tuple):
            error_data, status_code = llm_response
            return jsonify(error_data), status_code

        db_data = make_service_request(DB_SERVICE_URL, "process")
        if isinstance(db_data, tuple):
            error_data, status_code = db_data
            return jsonify(error_data), status_code

        # Use a dictionary to track unique URLs and keep the highest score for duplicates
        url_score_map = {}
        if isinstance(db_data, dict) and isinstance(db_data.get("message"), list):
            for item in db_data["message"]:
                if isinstance(item, dict) and "relevance_analysis" in item:
                    analysis = item["relevance_analysis"]
                    href_url = analysis.get("href_url", "")
                    score = float(analysis.get("score", 0))
                    
                    # Only keep the highest score for each URL
                    if href_url not in url_score_map or score > url_score_map[href_url]:
                        url_score_map[href_url] = score

        # Convert the unique URL map back to a list of dictionaries
        links = [{"url": url, "score": score} for url, score in url_score_map.items()]
        links.sort(key=lambda x: float(x["score"] or 0), reverse=True)

        return jsonify({
            "source_url": url,
            "keyword": keyword,
            "results": links,
            "count": len(links)
        })

    except Exception as e:
        logger.error("Error in scrape endpoint: %s", str(e), exc_info=True)
        return jsonify({
            "error": "scraping_failed",
            "message": "Unable to complete the scraping request. Please try again later.",
            "status": "error"
        }), 500


@app.route("/db/query")
def db_query():
    """Proxy database queries to the DB service."""
    try:
        return make_service_request(
            DB_SERVICE_URL, "query", method="GET", params=request.args
        )
    except Exception as e:
        return create_error_response(
            e, 503 if isinstance(e, requests.exceptions.RequestException) else 500
        )


@app.route("/db/query/href")
def db_query_href():
    """Proxy href URL queries to the DB service."""
    try:
        return make_service_request(
            DB_SERVICE_URL, "query/href", method="GET", params=request.args
        )
    except Exception as e:
        return create_error_response(
            e, 503 if isinstance(e, requests.exceptions.RequestException) else 500
        )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
