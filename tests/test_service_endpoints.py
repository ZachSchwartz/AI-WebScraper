"""Tests for the queue-draining and health endpoints each service exposes."""

# pylint: disable=missing-function-docstring,redefined-outer-name,unused-argument

import pytest
import redis
import scorer_main
from util import health_util


@pytest.fixture
def client(queue_manager):
    """The scorer app, draining the in-process queue."""
    scorer_main.app.config["TESTING"] = True
    return scorer_main.app.test_client()


def test_process_scores_everything_on_the_queue(client, queue_manager):
    queue_manager.publish_item(
        {"keyword": "harness", "processed_text": "harness buying guide", "href": "/a"}
    )

    response = client.post("/process")

    assert response.status_code == 200
    scored = response.json["message"]
    assert len(scored) == 1
    assert 0 <= scored[0]["relevance_analysis"]["score"] <= 1


def test_process_answers_an_empty_queue_with_an_empty_result(client):
    response = client.post("/process")

    assert response.status_code == 200
    assert response.json["message"] == []


def test_process_reports_a_queue_it_cannot_reach(client, monkeypatch):
    def unreachable(_processor):
        raise redis.RedisError("connection refused")

    monkeypatch.setattr(
        scorer_main.QueueManager,
        "process_queue",
        lambda self, processor: unreachable(processor),
    )

    response = client.post("/process")

    assert response.status_code == 500
    assert response.json["error"] == "scorer_processor_error"


def test_health_reports_a_reachable_queue(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json["status"] == "healthy"
    assert response.json["service"] == "scorer_processor"


def test_health_reports_an_unreachable_queue(client, monkeypatch):
    def refuse():
        raise redis.RedisError("connection refused")

    monkeypatch.setattr(
        health_util.QueueManager, "get_redis_client", classmethod(lambda cls: refuse())
    )

    response = client.get("/health")

    assert response.status_code == 500
    assert response.json["status"] == "unhealthy"
