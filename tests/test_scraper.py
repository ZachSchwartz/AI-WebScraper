"""Tests for the producer's fetching and HTML parsing."""

# pylint: disable=missing-function-docstring,redefined-outer-name,unused-argument

import pytest
import requests
import scraper
from scraper import (
    clean_text,
    fetch_page,
    fetch_with_requests,
    parse_content,
    process_url,
    scrape,
)
from util.url_util import UrlNotAllowed

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

    def failing_get(url, headers=None, timeout=None, allow_redirects=None):
        attempts.append(url)
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr(scraper.requests, "get", failing_get)
    monkeypatch.setattr(scraper.time, "sleep", lambda seconds: None)

    result = fetch_with_requests("https://example.com", HEADERS, 5, 3)

    assert len(attempts) == 3
    assert result["error"] == "request_failed"


def test_scrape_reports_missing_targets():
    assert scrape({"targets": []})["error"] == "missing_targets"


def test_robots_txt_is_read_from_the_domain_root(monkeypatch):
    requested = []

    class FakeParser:
        """Records the robots.txt location without touching the network."""

        def set_url(self, url):
            requested.append(url)

        def read(self):
            pass

        def can_fetch(self, user_agent, url):
            return True

    monkeypatch.setattr(scraper, "RobotFileParser", FakeParser)
    scraper.is_allowed_by_robots("https://example.com/docs/deep/page", "test-agent")

    assert requested == ["https://example.com/robots.txt"]


class FakeResponse:
    """Enough of a requests.Response for the redirect walk to act on."""

    def __init__(self, status_code=200, location=None, text="<html></html>"):
        self.status_code = status_code
        self.headers = {"Location": location} if location else {}
        self.text = text

    @property
    def is_redirect(self):
        return (
            self.status_code in (301, 302, 303, 307, 308) and "Location" in self.headers
        )

    def raise_for_status(self):
        pass


def responder(monkeypatch, *responses):
    """Serve the given responses in order, recording each URL requested."""
    requested = []
    remaining = list(responses)

    def fake_get(url, headers=None, timeout=None, allow_redirects=None):
        requested.append(url)
        return remaining.pop(0)

    monkeypatch.setattr(scraper.requests, "get", fake_get)
    return requested


def test_fetch_page_follows_a_redirect_that_stays_on_the_public_web(monkeypatch):
    requested = responder(
        monkeypatch,
        FakeResponse(302, location="https://example.com/moved"),
        FakeResponse(text="<html>arrived</html>"),
    )

    assert fetch_page("https://example.com", HEADERS, 5).text == "<html>arrived</html>"
    assert requested == ["https://example.com", "https://example.com/moved"]


def test_fetch_refuses_a_redirect_onto_the_private_network(
    allow_robots, monkeypatch, resolves_to
):
    responder(monkeypatch, FakeResponse(302, location="http://169.254.169.254/latest/"))
    resolves_to("169.254.169.254")

    result = fetch_with_requests("https://example.com", HEADERS, 5, 3)

    assert result["error"] == "url_not_allowed"


def test_fetch_page_gives_up_on_an_endless_redirect_chain(monkeypatch):
    responder(
        monkeypatch,
        *[FakeResponse(302, location="https://example.com/loop")] * 10,
    )

    with pytest.raises(UrlNotAllowed):
        fetch_page("https://example.com", HEADERS, 5)


def test_scrape_refuses_a_url_that_resolves_off_the_public_web(resolves_to):
    resolves_to("127.0.0.1")

    result = scrape(
        {"targets": [{"url": "http://localhost:5432", "keyword": "harness"}]}
    )

    assert result["error"] == "url_not_allowed"


def test_robots_txt_that_cannot_be_read_does_not_block_the_fetch(monkeypatch):
    def unreachable(self):
        raise OSError("connection refused")

    monkeypatch.setattr(scraper.RobotFileParser, "read", unreachable)

    assert scraper.is_allowed_by_robots("https://example.com", "test-agent") is True
