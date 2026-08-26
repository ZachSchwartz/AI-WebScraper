"""Tests for the producer's fetching and HTML parsing."""

# pylint: disable=missing-function-docstring,redefined-outer-name,unused-argument

import pytest
import requests
import scraper
from scraper import clean_text, fetch_with_requests, parse_content, process_url, scrape

HEADERS = {"User-Agent": "test-agent"}

SAMPLE_HTML = """
<html>
  <head>
    <title>Climbing Gear Reviews</title>
    <meta name="description" content="In depth reviews of climbing harnesses, ropes and belay devices.">
  </head>
  <body>
    <p>Our top rated harnesses this season.</p>
    <a href="/reviews/harness-guide" title="Harness guide">Harness buying guide</a>
    <p>Ropes are covered separately.</p>
    <a>Click here</a>
    <a href="https://shop.example.com/ropes">Ropes</a>
  </body>
</html>
"""

TARGET_CONFIG = {
    "url": "https://example.com",
    "keyword": "harness",
    "container_selector": "body",
}


@pytest.fixture
def allow_robots(monkeypatch):
    """Bypass the network call robots.txt checking would otherwise make."""
    monkeypatch.setattr(scraper.RobotFileParser, "read", lambda self: None)
    monkeypatch.setattr(
        scraper.RobotFileParser, "can_fetch", lambda self, agent, url: True
    )


def test_parse_content_extracts_links_with_surrounding_context():
    results = parse_content(SAMPLE_HTML, TARGET_CONFIG)

    assert [item["href"] for item in results] == [
        "/reviews/harness-guide",
        "https://shop.example.com/ropes",
    ]

    guide = results[0]
    assert guide["keyword"] == "harness"
    assert guide["source_url"] == "https://example.com"
    assert guide["context"]["previous_text"] == "Our top rated harnesses this season."
    assert guide["context"]["next_text"] == "Ropes are covered separately."

    text = guide["processed_text"]
    assert "Harness buying guide" in text
    assert "Climbing Gear Reviews" in text
    assert "belay devices" in text


def test_parse_content_survives_unusable_html():
    assert parse_content("", TARGET_CONFIG) == []
    assert parse_content("just a bare string", TARGET_CONFIG) == []


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  Harness guide  ", "Harness guide"),
        ("Click here", None),
        ("Please turn JavaScript on to continue", None),
        ("", None),
    ],
)
def test_clean_text_strips_whitespace_and_drops_boilerplate(raw, expected):
    assert clean_text(raw) == expected


def test_process_url_normalizes_domain_and_drops_generic_segments():
    assert process_url("https://www.example.com/index/gear-guide", set()) == [
        "example",
        "gear",
        "guide",
    ]


def test_process_url_reports_each_domain_only_once():
    seen = set()
    process_url("https://example.com/harnesses", seen)

    assert process_url("https://example.com/ropes", seen) == ["ropes"]


def test_fetch_stops_before_requesting_a_disallowed_url(monkeypatch):
    monkeypatch.setattr(scraper.RobotFileParser, "read", lambda self: None)
    monkeypatch.setattr(
        scraper.RobotFileParser, "can_fetch", lambda self, agent, url: False
    )
    monkeypatch.setattr(
        scraper.requests, "get", lambda *a, **k: pytest.fail("fetched a disallowed URL")
    )

    result = fetch_with_requests("https://example.com", HEADERS, 5, 3)

    assert result["error"] == "robots_txt_error"


def test_fetch_retries_then_reports_failure(allow_robots, monkeypatch):
    attempts = []

    def failing_get(url, headers=None, timeout=None):
        attempts.append(url)
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr(scraper.requests, "get", failing_get)
    monkeypatch.setattr(scraper.time, "sleep", lambda seconds: None)

    result = fetch_with_requests("https://example.com", HEADERS, 5, 3)

    assert len(attempts) == 3
    assert result["error"] == "request_failed"


def test_scrape_reports_missing_targets():
    assert scrape({"targets": []})["error"] == "missing_targets"
