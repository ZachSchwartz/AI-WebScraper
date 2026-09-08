"""
Web service module that provides a Flask-based API for web scraping and data processing.
This service coordinates between producer, scorer, and database services to scrape, analyze,
and store web content based on user queries.
"""

import os
import uuid
import logging
from typing import Dict, Optional
import requests
from flask import Flask, render_template, request, jsonify, abort
from werkzeug.exceptions import HTTPException

from util.health_util import perform_health_check
from util.url_util import UrlNotAllowed, assert_fetchable

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

PRODUCER_SERVICE_URL = os.getenv("PRODUCER_SERVICE_URL", "http://producer:5000")
SCORER_SERVICE_URL = os.getenv("SCORER_SERVICE_URL", "http://scorer:5000")
DB_SERVICE_URL = os.getenv("DB_SERVICE_URL", "http://db_processor:5000")

SERVICE_TIMEOUT = int(os.getenv("SERVICE_TIMEOUT", "10"))
PIPELINE_TIMEOUT = int(os.getenv("PIPELINE_TIMEOUT", "180"))


def sort_links(data: dict):
    """Sorts links by relevance score and returns a list of dictionaries with url and score."""
    url_score_map: Dict[str, float] = {}
    if isinstance(data, dict) and isinstance(data.get("message"), list):
        for item in data["message"]:
            if isinstance(item, dict) and "relevance_analysis" in item:
                analysis = item["relevance_analysis"]
                href_url = analysis.get("href_url", "")
                score = float(analysis.get("score", 0))

                if href_url not in url_score_map or score > url_score_map[href_url]:
                    url_score_map[href_url] = score

    return [
        {"url": url, "score": score}
        for url, score in sorted(
            url_score_map.items(), key=lambda pair: pair[1], reverse=True
        )
    ]


GENERIC_ERROR_MESSAGE = "Unable to complete the request. Please try again later."


def is_refusal(exception: HTTPException) -> bool:
    """Whether the failure answers the request rather than reporting on us."""
    return exception.code is not None and 400 <= exception.code < 500


class ServiceFailure(HTTPException):
    """A failure a downstream service reported, under the name it gave it.

    Aborting would keep only the description, which loses the difference
    between a link that is not stored and a service that is not answering.
    """

    def __init__(self, code: int, error: str, description: str):
        super().__init__(description=description)
        self.code = code
        self.error = error


def error_response(error: str, message: str, status_code: int):
    """The one shape every failure this service reports takes."""
    return (
        jsonify({"error": error, "message": message, "status": "error"}),
        status_code,
    )


def create_error_response(exception: Exception, error: str, status_code: int):
    """Report a failure the request ran into, saying only what the caller may know.

    A refusal a downstream service wrote is the caller's own answer, so its
    description is passed on. Anything else is an internal failure whose text
    describes this stack rather than the request, and the caller learns only
    that it failed; the detail goes to the log instead.
    """
    logger.error("%s: %s", exception.__class__.__name__, exception, exc_info=True)

    message = GENERIC_ERROR_MESSAGE
    if (
        isinstance(exception, HTTPException)
        and exception.description
        and is_refusal(exception)
    ):
        message = exception.description

    return error_response(error, message, status_code)


def make_service_request(
    service_url: str,
    endpoint: str,
    *,
    json: Optional[dict] = None,
    method: str = "POST",
    params: Optional[dict] = None,
    timeout: int = SERVICE_TIMEOUT,
):
    """Make a standardized request to a service

    Args:
        service_url (str): Base URL of the service
        endpoint (str): Service endpoint to call
        json (dict, optional): JSON data to send in request body
        method (str, optional): HTTP method to use. Defaults to "POST"
        params (dict, optional): Query parameters to include in URL
        timeout (int, optional): Seconds to wait for the service to answer

    Returns:
        dict: Response data if successful

    Raises:
        HTTPException: If the request fails or returns an error
    """
    url = f"{service_url}/{endpoint.lstrip('/')}"
    response = requests.request(
        method=method, url=url, json=json, params=params, timeout=timeout
    )

    try:
        data = response.json()
    except ValueError:
        return abort(500, description="Invalid response from service")

    logger.info("Service response from %s: %s", url, data)

    if not response.ok or (isinstance(data, dict) and "error" in data):
        raise ServiceFailure(
            response.status_code if not response.ok else 500,
            data.get("error", "service_error"),
            data.get("message", "Service request failed"),
        )

    return data


@app.route("/")
def index():
    """Render the main application interface.

    Returns:
        str: Rendered HTML template for the index page.
    """
    return render_template("index.html")


@app.route("/health", methods=["GET"])
def health_check():
    """Report whether this service is up."""
    return perform_health_check("web_service")


@app.route("/api/scrape", methods=["POST"])
def scrape():
    """Process a web scraping request by coordinating with multiple services.

    The function orchestrates the following steps:
    1. Sends URL and keyword to producer service for scraping
    2. Triggers scorer service for content analysis
    3. Retrieves processed results from database service
    4. Sorts and returns relevant links based on relevance scores

    Each request carries a job id so that results are scoped to this scrape.
    Without it, items a previous run left in the queue would be reported here.

    Returns:
        tuple: JSON response containing scraped results and HTTP status code
    """
    data = request.get_json(silent=True) or {}
    url = data.get("url")
    keyword = data.get("keyword")

    if not url or not keyword:
        return error_response(
            "missing_parameter", "Both url and keyword are required.", 400
        )

    try:
        url = assert_fetchable(url)
    except UrlNotAllowed as error:
        logger.warning("Rejected scrape of %s: %s", url, error)
        return error_response("invalid_url", str(error), 400)

    job_id = str(uuid.uuid4())
    logger.info("Starting scrape job %s of %s for %s", job_id, url, keyword)

    try:
        make_service_request(
            PRODUCER_SERVICE_URL,
            "scrape",
            json={"url": url, "keyword": keyword, "job_id": job_id},
            timeout=PIPELINE_TIMEOUT,
        )
        make_service_request(
            SCORER_SERVICE_URL,
            "process",
            json={"job_id": job_id},
            timeout=PIPELINE_TIMEOUT,
        )
        db_data = make_service_request(
            DB_SERVICE_URL,
            "process",
            json={"job_id": job_id},
            timeout=PIPELINE_TIMEOUT,
        )

        links = sort_links(db_data)

        return jsonify(
            {
                "source_url": url,
                "keyword": keyword,
                "job_id": job_id,
                "results": links,
                "count": len(links),
            }
        )

    except Exception as error:
        return create_error_response(error, "scraping_failed", 500)


def query_failure_status(error: Exception) -> int:
    """The code a database query that did not answer reports.

    A refusal the database service wrote is the caller's answer, code and all;
    a service that could not be reached at all is this stack being unavailable
    rather than the query being wrong.
    """
    if isinstance(error, HTTPException):
        return error.code or 500
    return 503 if isinstance(error, requests.exceptions.RequestException) else 500


def query_failure_error(error: Exception) -> str:
    """The name a database query that did not answer reports.

    A refusal the database service wrote is the caller's answer, name and all,
    so a link that is not stored reads differently from a parameter that is
    missing. An internal failure keeps the generic name, since its own says
    nothing the caller can act on.
    """
    if isinstance(error, ServiceFailure) and is_refusal(error):
        return error.error
    return "query_failed"


def proxy_to_db(endpoint: str):
    """Pass the request's query parameters through to the database service."""
    try:
        return make_service_request(
            DB_SERVICE_URL, endpoint, method="GET", params=request.args
        )
    except Exception as error:
        return create_error_response(
            error, query_failure_error(error), query_failure_status(error)
        )


@app.route("/db/query")
def db_query():
    """Proxy database queries to the DB service."""
    return proxy_to_db("query")


@app.route("/db/query/href")
def db_query_href():
    """Proxy href URL queries to the DB service."""
    return proxy_to_db("query/href")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
