"""Tests for the URL canonicalization and fetch policy the services share."""

# pylint: disable=missing-function-docstring,redefined-outer-name,unused-argument

import socket
import pytest
from util.url_util import UrlNotAllowed, assert_fetchable, normalize_url


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://example.com", "https://example.com/"),
        ("https://example.com/", "https://example.com/"),
        ("example.com", "https://example.com/"),
        ("HTTPS://Example.COM/Path", "https://example.com/Path"),
        ("https://example.com/page#section", "https://example.com/page"),
        ("https://example.com/search?q=rope", "https://example.com/search?q=rope"),
        ("mailto:shop@example.com", "mailto:shop@example.com"),
        ("tel:15550100", "tel:15550100"),
    ],
)
def test_normalize_url_gives_one_page_one_form(raw, expected):
    assert normalize_url(raw) == expected


def test_assert_fetchable_returns_the_normalized_url():
    assert assert_fetchable("HTTPS://Example.COM/Path#frag") == (
        "https://example.com/Path"
    )


@pytest.mark.parametrize(
    "url, address",
    [
        ("http://10.0.0.5/admin", "10.0.0.5"),
        ("http://192.168.1.1/", "192.168.1.1"),
        ("http://172.16.0.9/", "172.16.0.9"),
        ("http://169.254.169.254/latest/meta-data/", "169.254.169.254"),
        ("http://127.0.0.1:6379/", "127.0.0.1"),
        ("https://internal.example.com/", "10.1.2.3"),
    ],
)
def test_assert_fetchable_rejects_the_private_network(url, address, resolves_to):
    resolves_to(address)

    with pytest.raises(UrlNotAllowed):
        assert_fetchable(url)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/archive"])
def test_assert_fetchable_rejects_schemes_that_are_not_web_pages(url):
    with pytest.raises(UrlNotAllowed):
        assert_fetchable(url)


def test_assert_fetchable_rejects_a_host_that_does_not_resolve(monkeypatch):
    def unresolvable(*args, **kwargs):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", unresolvable)

    with pytest.raises(UrlNotAllowed):
        assert_fetchable("https://nonexistent.invalid/")


def test_assert_fetchable_allows_an_ordinary_public_page():
    assert assert_fetchable("https://example.com/guide") == "https://example.com/guide"
