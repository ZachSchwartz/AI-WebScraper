"""Tests for the producer's HTTP surface and queue publishing."""

# pylint: disable=missing-function-docstring,redefined-outer-name,unused-argument

import producer_main
import pytest
from producer_main import app, run_scraper

SCRAPED = {
    "results": [
        {"href": "/harness-guide", "processed_text": "harness guide"},
        {"href": "/ropes", "processed_text": "ropes"},
    ]
}


@pytest.fixture
def client(queue_manager):
    """The producer app, publishing into the in-process queue."""
    app.config["TESTING"] = True
    return app.test_client()


def scraping_returns(monkeypatch, result):
    """Make the scraper produce a fixed result without touching the network."""
    monkeypatch.setattr(producer_main, "scrape", lambda config: result)


def test_run_scraper_publishes_every_link_tagged_with_the_job(
    queue_manager, monkeypatch
):
    scraping_returns(monkeypatch, SCRAPED)

    result = run_scraper(queue_manager, "https://example.com", "harness", "job-1")

    assert result == {
        "job_id": "job-1",
        "url": "https://example.com",
        "published": 2,
    }
    assert [queue_manager.get_item()["job_id"] for _ in range(2)] == ["job-1", "job-1"]


def test_a_page_with_no_links_is_a_count_of_zero_not_a_failure(
    queue_manager, monkeypatch
):
    scraping_returns(monkeypatch, {"results": []})

    result = run_scraper(queue_manager, "https://example.com", "harness", "job-1")

    assert result["published"] == 0
    assert "error" not in result


def test_run_scraper_leaves_the_shared_config_untouched(queue_manager, monkeypatch):
    scraping_returns(monkeypatch, SCRAPED)

    run_scraper(queue_manager, "https://example.com", "harness", "job-1")

    assert producer_main.SCRAPER_CONFIG["targets"][0]["url"] == ""
    assert producer_main.SCRAPER_CONFIG["targets"][0]["keyword"] == ""


def test_scrape_endpoint_answers_with_what_it_published(client, monkeypatch):
    scraping_returns(monkeypatch, SCRAPED)

    response = client.post(
        "/scrape",
        json={"url": "https://example.com", "keyword": "harness", "job_id": "job-1"},
    )

    assert response.status_code == 200
    assert response.json["published"] == 2


def test_scrape_endpoint_answers_a_link_free_page_with_success(client, monkeypatch):
    scraping_returns(monkeypatch, {"results": []})

    response = client.post(
        "/scrape", json={"url": "https://example.com", "keyword": "harness"}
    )

    assert response.status_code == 200
    assert response.json["published"] == 0


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"url": "https://example.com"},
        {"keyword": "harness"},
        {"url": "", "keyword": "harness"},
    ],
)
def test_scrape_endpoint_rejects_an_incomplete_request(client, body):
    response = client.post("/scrape", json=body)

    assert response.status_code == 400
    assert response.json["error"] == "missing_parameter"


def test_scrape_endpoint_rejects_a_request_with_no_body(client):
    response = client.post("/scrape")

    assert response.status_code == 400


def test_scrape_endpoint_reports_a_scraping_failure(client, monkeypatch):
    scraping_returns(
        monkeypatch, {"error": "robots_txt_error", "message": "not allowed"}
    )

    response = client.post(
        "/scrape", json={"url": "https://example.com", "keyword": "harness"}
    )

    assert response.status_code == 400
    assert response.json["error"] == "robots_txt_error"
