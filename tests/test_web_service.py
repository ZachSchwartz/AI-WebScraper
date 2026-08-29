"""Tests for the web service's orchestration and error handling."""

# pylint: disable=missing-function-docstring,redefined-outer-name,unused-argument

import re

import app as web_app
import pytest
import requests
from werkzeug.exceptions import BadRequest, NotFound
from app import app, sort_links


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def unavailable_service(monkeypatch):
    def failing(*args, **kwargs):
        raise requests.exceptions.ConnectionError("service unavailable")

    monkeypatch.setattr(web_app, "make_service_request", failing)


def test_sort_links_keeps_the_highest_score_per_url():
    data = {
        "message": [
            {"relevance_analysis": {"href_url": "https://example.com/a", "score": 0.2}},
            {"relevance_analysis": {"href_url": "https://example.com/a", "score": 0.9}},
            {"relevance_analysis": {"href_url": "https://example.com/b", "score": 0.5}},
            {"no_analysis_here": True},
        ]
    }

    assert sort_links(data) == [
        {"url": "https://example.com/a", "score": 0.9},
        {"url": "https://example.com/b", "score": 0.5},
    ]


def test_sort_links_ignores_unexpected_payloads():
    assert sort_links({"message": "not a list"}) == []


def test_scrape_endpoint_calls_each_service_and_ranks_results(client, monkeypatch):
    endpoints = []

    def fake_request(service_url, endpoint, **kwargs):
        endpoints.append(endpoint)
        return {
            "message": [
                {
                    "relevance_analysis": {
                        "href_url": "https://example.com/a",
                        "score": 0.4,
                    }
                },
                {
                    "relevance_analysis": {
                        "href_url": "https://example.com/b",
                        "score": 0.8,
                    }
                },
            ]
        }

    monkeypatch.setattr(web_app, "make_service_request", fake_request)

    response = client.post(
        "/api/scrape", json={"url": "https://example.com", "keyword": "harness"}
    )

    assert response.status_code == 200
    assert endpoints == ["scrape", "process", "process"]
    assert response.json["count"] == 2
    assert [item["url"] for item in response.json["results"]] == [
        "https://example.com/b",
        "https://example.com/a",
    ]


def test_every_stage_is_told_which_job_it_is_working_on(client, monkeypatch):
    """Each stage drains its own job's queue, so all three need the id."""
    jobs = []

    def fake_request(service_url, endpoint, **kwargs):
        jobs.append((kwargs.get("json") or {}).get("job_id"))
        return {"message": []}

    monkeypatch.setattr(web_app, "make_service_request", fake_request)

    response = client.post(
        "/api/scrape", json={"url": "https://example.com", "keyword": "harness"}
    )

    job_id = response.json["job_id"]
    assert jobs == [job_id, job_id, job_id]


def test_scrape_endpoint_tags_the_producer_and_db_calls_with_one_job_id(
    client, monkeypatch
):
    payloads = []

    def fake_request(service_url, endpoint, **kwargs):
        payloads.append(kwargs.get("json"))
        return {"message": []}

    monkeypatch.setattr(web_app, "make_service_request", fake_request)

    response = client.post(
        "/api/scrape", json={"url": "https://example.com", "keyword": "harness"}
    )

    job_id = response.json["job_id"]
    assert payloads[0]["job_id"] == job_id
    assert payloads[2]["job_id"] == job_id


def test_scrape_endpoint_issues_a_fresh_job_id_per_request(client, monkeypatch):
    monkeypatch.setattr(
        web_app, "make_service_request", lambda *args, **kwargs: {"message": []}
    )
    request_body = {"url": "https://example.com", "keyword": "harness"}

    first = client.post("/api/scrape", json=request_body)
    second = client.post("/api/scrape", json=request_body)

    assert first.json["job_id"] != second.json["job_id"]


def test_scrape_endpoint_reports_a_failed_service(client, unavailable_service):
    response = client.post(
        "/api/scrape", json={"url": "https://example.com", "keyword": "harness"}
    )

    assert response.status_code == 500
    assert response.json["error"] == "scraping_failed"


def test_db_query_href_forwards_a_missing_record_as_not_found(client, monkeypatch):
    def not_found(*args, **kwargs):
        raise NotFound("No item found with the specified href URL")

    monkeypatch.setattr(web_app, "make_service_request", not_found)

    response = client.get(
        "/db/query/href", query_string={"href_url": "https://nope.example/missing"}
    )

    assert response.status_code == 404
    assert response.json["message"] == "No item found with the specified href URL"


def test_db_query_returns_service_unavailable_when_the_db_service_is_down(
    client, unavailable_service
):
    response = client.get("/db/query", query_string={"keyword": "harness"})

    assert response.status_code == 503
    assert response.json["status"] == "error"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"url": "https://example.com"},
        {"keyword": "harness"},
        {"url": "", "keyword": "harness"},
    ],
)
def test_scrape_endpoint_rejects_an_incomplete_request(client, body, monkeypatch):
    monkeypatch.setattr(
        web_app, "make_service_request", lambda *a, **k: pytest.fail("called a service")
    )

    response = client.post("/api/scrape", json=body)

    assert response.status_code == 400
    assert response.json["error"] == "missing_parameter"


def test_scrape_endpoint_rejects_a_request_with_no_body(client):
    assert client.post("/api/scrape").status_code == 400


@pytest.mark.parametrize(
    "url, address",
    [
        ("http://169.254.169.254/latest/meta-data/", "169.254.169.254"),
        ("http://postgres:5432/", "172.18.0.2"),
        ("http://localhost:6379/", "127.0.0.1"),
    ],
)
def test_scrape_endpoint_refuses_to_reach_into_the_private_network(
    client, url, address, resolves_to, monkeypatch
):
    monkeypatch.setattr(
        web_app, "make_service_request", lambda *a, **k: pytest.fail("called a service")
    )
    resolves_to(address)

    response = client.post("/api/scrape", json={"url": url, "keyword": "harness"})

    assert response.status_code == 400
    assert response.json["error"] == "invalid_url"


def test_the_pipeline_gets_a_longer_budget_than_a_database_query(client, monkeypatch):
    timeouts = []

    def record_timeout(service_url, endpoint, **kwargs):
        timeouts.append(kwargs.get("timeout"))
        return {"message": []}

    monkeypatch.setattr(web_app, "make_service_request", record_timeout)

    client.post("/api/scrape", json={"url": "https://example.com", "keyword": "rope"})

    assert timeouts == [web_app.PIPELINE_TIMEOUT] * 3
    assert web_app.PIPELINE_TIMEOUT > web_app.SERVICE_TIMEOUT


def test_the_scrape_is_forwarded_under_its_normalized_url(client, monkeypatch):
    payloads = []

    def record(service_url, endpoint, **kwargs):
        payloads.append(kwargs.get("json"))
        return {"message": []}

    monkeypatch.setattr(web_app, "make_service_request", record)

    response = client.post(
        "/api/scrape", json={"url": "Example.COM/Guide", "keyword": "rope"}
    )

    assert payloads[0]["url"] == "https://example.com/Guide"
    assert response.json["source_url"] == "https://example.com/Guide"


def test_the_page_serves_every_asset_it_needs_itself(client):
    """A CDN would be a runtime dependency nothing else in the stack has."""
    page = client.get("/").get_data(as_text=True)
    assets = re.findall(r"<(?:link|script)[^>]*\s(?:href|src)=\"([^\"]+)\"", page)

    assert assets == ["/static/vendor/bootstrap.min.css"]
    assert client.get(assets[0]).status_code == 200


def test_the_page_never_builds_a_result_out_of_markup(client):
    """Results carry scraped text, so they are written as nodes rather than HTML."""
    page = client.get("/").get_data(as_text=True)

    assert "innerHTML" not in page


def test_health_reports_the_service_is_up(client):
    """The web service answers for its own liveness, holding no queue of its own."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json["status"] == "healthy"
    assert response.json["service"] == "web_service"


def test_an_internal_failure_is_reported_without_describing_the_stack(
    client, monkeypatch
):
    """The text of an internal error names this code, not the user's request."""

    def leak(*args, **kwargs):
        raise RuntimeError("psycopg2 could not connect to postgres:5432")

    monkeypatch.setattr(web_app, "make_service_request", leak)

    response = client.get("/db/query", query_string={"keyword": "harness"})

    assert response.status_code == 500
    assert response.json["message"] == web_app.GENERIC_ERROR_MESSAGE


def test_a_failed_pipeline_step_reports_what_the_service_refused(client, monkeypatch):
    def refuse(*args, **kwargs):
        raise BadRequest("This website's robots.txt file does not allow scraping")

    monkeypatch.setattr(web_app, "make_service_request", refuse)

    response = client.post(
        "/api/scrape", json={"url": "https://example.com", "keyword": "harness"}
    )

    assert response.status_code == 500
    assert (
        response.json["message"]
        == "This website's robots.txt file does not allow scraping"
    )
