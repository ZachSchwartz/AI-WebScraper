"""Tests for the Redis queue the three services hand work through."""

# pylint: disable=missing-function-docstring,redefined-outer-name,unused-argument

import json
from util.queue_util import QUEUE_TTL_SECONDS, QueueManager, scoped_queue_name


def publish_all(manager, items):
    """Put every item on the queue the manager reads from."""
    for item in items:
        manager.publish_item(item)


def read_processed(manager):
    """Drain the processed queue the manager writes to."""
    raw = manager.redis_client.lrange(manager.processed_queue_name, 0, -1)
    return [json.loads(entry) for entry in raw]


def test_published_items_come_back_in_the_order_they_were_sent(queue_manager):
    publish_all(queue_manager, [{"href": "/a"}, {"href": "/b"}])

    assert queue_manager.get_item() == {"href": "/a"}
    assert queue_manager.get_item() == {"href": "/b"}
    assert queue_manager.get_item() is None


def test_get_batch_stops_at_the_batch_size(queue_manager):
    queue_manager.batch_size = 2
    publish_all(queue_manager, [{"href": f"/{index}"} for index in range(5)])

    assert len(queue_manager.get_batch()) == 2


def test_get_batch_returns_what_is_there_when_the_queue_runs_short(queue_manager):
    publish_all(queue_manager, [{"href": "/only"}])

    assert queue_manager.get_batch() == [{"href": "/only"}]


def test_process_queue_forwards_every_processed_item(queue_manager):
    publish_all(queue_manager, [{"href": "/a"}, {"href": "/b"}])

    processed = queue_manager.process_queue(lambda item: {**item, "scored": True})

    assert len(processed) == 2
    assert read_processed(queue_manager) == [
        {"href": "/b", "scored": True},
        {"href": "/a", "scored": True},
    ]


def test_process_queue_drops_items_the_processor_rejects(queue_manager):
    publish_all(queue_manager, [{"href": "/good"}, {"href": "/bad"}])

    def reject_one(item):
        if item["href"] == "/bad":
            raise RuntimeError("could not be stored")
        return item

    processed = queue_manager.process_queue(reject_one)

    assert processed == [{"href": "/good"}]
    assert read_processed(queue_manager) == [{"href": "/good"}]


def test_process_queue_gives_up_on_a_queue_that_stays_empty(queue_manager):
    polls = []
    queue_manager.max_idle_polls = 3
    original_get_batch = queue_manager.get_batch
    queue_manager.get_batch = lambda: polls.append(1) or original_get_batch()

    assert queue_manager.process_queue(lambda item: item) == []
    assert len(polls) == queue_manager.max_idle_polls


def test_process_queue_stops_at_the_iteration_cap(queue_manager):
    queue_manager.max_iterations = 2
    queue_manager.batch_size = 1
    publish_all(queue_manager, [{"href": f"/{index}"} for index in range(5)])

    assert len(queue_manager.process_queue(lambda item: item)) == 2


def test_publishing_an_unserializable_item_reports_failure(queue_manager):
    assert queue_manager.publish_item({"href": object()}) is False


def test_get_redis_config_reads_the_environment(monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "cache")
    monkeypatch.setenv("REDIS_PORT", "6380")

    config = QueueManager.get_redis_config(queue_name="scored", wait_time=2)

    assert config["host"] == "cache"
    assert config["port"] == 6380
    assert config["queue_name"] == "scored"
    assert config["wait_time"] == 2


def test_the_processed_queue_is_named_after_the_source_queue(queue_manager):
    assert queue_manager.processed_queue_name == "scraped_items_processed"


def test_a_job_gets_queue_keys_of_its_own(queue_manager):
    scoped = QueueManager({"queue_name": "scraped_items", "job_id": "job-1"})

    assert scoped.queue_name == "scraped_items:job-1"
    assert scoped.processed_queue_name == "scraped_items_processed:job-1"


def test_two_jobs_do_not_read_each_others_items(queue_manager):
    first = QueueManager({"queue_name": "scraped_items", "job_id": "job-1"})
    second = QueueManager({"queue_name": "scraped_items", "job_id": "job-2"})

    first.publish_item({"href": "/first"})
    second.publish_item({"href": "/second"})

    assert first.get_item() == {"href": "/first"}
    assert first.get_item() is None
    assert second.get_item() == {"href": "/second"}


def test_a_caller_with_no_job_keeps_the_shared_key():
    assert scoped_queue_name("scraped_items", None) == "scraped_items"


def test_a_published_key_expires_so_an_abandoned_job_clears_itself(queue_manager):
    queue_manager.publish_item({"href": "/a"})

    ttl = queue_manager.redis_client.ttl(queue_manager.queue_name)

    assert 0 < ttl <= QUEUE_TTL_SECONDS


def test_the_last_stage_stores_its_items_without_forwarding_them(queue_manager):
    publish_all(queue_manager, [{"href": "/a"}])

    processed = queue_manager.process_queue(lambda item: item, forward=False)

    assert processed == [{"href": "/a"}]
    assert read_processed(queue_manager) == []
