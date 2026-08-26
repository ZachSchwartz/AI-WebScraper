"""Tests for the web service's orchestration and error handling."""

# pylint: disable=missing-function-docstring,redefined-outer-name,unused-argument

import app as web_app
import pytest
import requests
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


def test_scrape_endpoint_reports_a_failed_service(client, unavailable_service):
    response = client.post(
        "/api/scrape", json={"url": "https://example.com", "keyword": "harness"}
    )

    assert response.status_code == 500
    assert response.json["error"] == "scraping_failed"


def test_db_query_returns_service_unavailable_when_the_db_service_is_down(
    client, unavailable_service
):
    response = client.get("/db/query", query_string={"keyword": "harness"})

    assert response.status_code == 503
    assert response.json["status"] == "error"
