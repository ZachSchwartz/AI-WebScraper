"""Tests for the database service's query endpoints."""

# pylint: disable=missing-function-docstring,redefined-outer-name,unused-argument

import json

import db_main
import pytest
import sqlalchemy as sa
from db_processor import Base, DatabaseProcessor

STORED = [
    {
        "keyword": "harness",
        "source_url": "https://example.com/",
        "href_url": "https://example.com/harness-guide",
        "score": 0.9,
    },
    {
        "keyword": "harness",
        "source_url": "https://example.com/",
        "href_url": "https://example.com/ropes",
        "score": 0.2,
    },
    {
        "keyword": "rope",
        "source_url": "https://other.example/",
        "href_url": "https://other.example/rope",
        "score": 0.5,
    },
]


@pytest.fixture
def processor(monkeypatch):
    """A processor on a throwaway database, wired into the service."""
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    processor = DatabaseProcessor(engine=engine)

    monkeypatch.setattr(db_main, "DatabaseProcessor", lambda: processor)
    yield processor
    engine.dispose()


@pytest.fixture
def client(processor):
    """The database app, serving the stored rows."""
    for analysis in STORED:
        processor.process_item({"job_id": "job-1", "relevance_analysis": analysis})

    db_main.app.config["TESTING"] = True
    return db_main.app.test_client()


def test_query_by_keyword_returns_matches_ranked_by_score(client):
    response = client.get("/query", query_string={"keyword": "harness"})

    assert response.status_code == 200
    assert response.json["count"] == 2
    assert [item["href_url"] for item in response.json["items"]] == [
        "https://example.com/harness-guide",
        "https://example.com/ropes",
    ]


def test_query_by_source_url_accepts_an_uncanonical_url(client):
    response = client.get("/query", query_string={"source_url": "Example.COM"})

    assert response.json["count"] == 2


def test_query_narrows_when_both_filters_are_given(client):
    response = client.get(
        "/query",
        query_string={"keyword": "rope", "source_url": "https://other.example/"},
    )

    assert response.json["count"] == 1


def test_query_with_no_match_returns_an_empty_list(client):
    response = client.get("/query", query_string={"keyword": "crampons"})

    assert response.status_code == 200
    assert response.json == {"items": [], "count": 0}


def test_query_by_href_returns_the_link_and_where_it_was_found(client):
    response = client.get(
        "/query/href", query_string={"href_url": "https://example.com/ropes"}
    )

    assert response.status_code == 200
    assert response.json == {
        "href_url": "https://example.com/ropes",
        "source_url": "https://example.com/",
        "keyword": "harness",
        "relevance_score": 0.2,
    }


def test_query_by_href_requires_the_parameter(client):
    response = client.get("/query/href")

    assert response.status_code == 400
    assert response.json["error"] == "missing_parameter"


def test_query_by_href_reports_a_link_it_has_never_seen(client):
    response = client.get(
        "/query/href", query_string={"href_url": "https://nope.example/missing"}
    )

    assert response.status_code == 404
    assert response.json["error"] == "href_not_found"


def queue(queue_manager, *items):
    """Put items on the processed queue the database service reads."""
    for item in items:
        queue_manager.redis_client.lpush("scraped_items_processed", json.dumps(item))


@pytest.fixture
def process_client(processor):
    """The database app, with nothing stored yet."""
    db_main.app.config["TESTING"] = True
    return db_main.app.test_client()


def test_process_stores_the_queue_and_reports_only_this_job(
    process_client, queue_manager, scored
):
    queue(
        queue_manager,
        scored("https://example.com/a"),
        scored("https://example.com/b", job_id="job-2"),
    )

    response = process_client.post("/process", json={"job_id": "job-1"})

    assert response.status_code == 200
    assert [
        item["relevance_analysis"]["href_url"] for item in response.json["message"]
    ] == ["https://example.com/a"]


def test_process_does_not_report_a_link_it_could_not_store(
    process_client, queue_manager
):
    queue(queue_manager, {"job_id": "job-1", "relevance_analysis": {}})

    response = process_client.post("/process", json={"job_id": "job-1"})

    assert response.status_code == 200
    assert response.json["message"] == []
