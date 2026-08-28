"""
Shared test fixtures.

The scorer service imports torch and sentence-transformers at module level, which
together weigh over a gigabyte and download a model on first use. The tests
substitute a deterministic stand-in instead: embeddings are hashed bag-of-words
vectors, so cosine similarity still rises with shared vocabulary and the scoring
logic can be exercised without the real model.
"""

# pylint: disable=missing-function-docstring,unused-argument,import-outside-toplevel

import os
import socket
import sys
import tempfile
import types
import zlib
import fakeredis
import numpy as np
import pytest

EMBEDDING_DIM = 256
PUBLIC_ADDRESS = "93.184.216.34"


def _encode(text: str) -> np.ndarray:
    """Embed text as a hashed bag of words."""
    vector = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    for word in text.lower().split():
        vector[zlib.crc32(word.encode()) % EMBEDDING_DIM] += 1.0
    return vector


def _cos_sim(left: np.ndarray, right: np.ndarray) -> np.float32:
    denominator = np.linalg.norm(left) * np.linalg.norm(right)
    if denominator == 0:
        return np.float32(0.0)
    return np.float32(np.dot(left, right) / denominator)


class FakeSentenceTransformer:
    """Stand-in for SentenceTransformer that records the texts it embeds."""

    def __init__(self, model_name: str, cache_folder: str = None):
        self.model_name = model_name
        self.cache_folder = cache_folder
        self.device = "cpu"
        self.encoded = []

    def to(self, device: str) -> "FakeSentenceTransformer":
        self.device = device
        return self

    def encode(self, texts, convert_to_numpy: bool = True) -> np.ndarray:
        """Embed one text or a batch of them, as the real model does."""
        if isinstance(texts, str):
            self.encoded.append(texts)
            return _encode(texts)

        self.encoded.extend(texts)
        return np.stack([_encode(text) for text in texts])


def _redirect_model_cache() -> None:
    """Point the model cache somewhere writable.

    The scorer defaults it to an absolute container path and builds a processor
    at import time, so this has to be set before any test imports that module.
    """
    os.environ.setdefault("MODEL_CACHE_DIR", tempfile.mkdtemp(prefix="scorer-cache-"))


def _install_stubs() -> None:
    """Register stub modules before scorer_processor is imported."""
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    sys.modules.setdefault("torch", torch)

    sentence_transformers = types.ModuleType("sentence_transformers")
    sentence_transformers.SentenceTransformer = FakeSentenceTransformer
    sentence_transformers.util = types.SimpleNamespace(cos_sim=_cos_sim)
    sys.modules.setdefault("sentence_transformers", sentence_transformers)


_redirect_model_cache()
_install_stubs()


@pytest.fixture
def scorer_processor(tmp_path, monkeypatch):
    """A ScorerProcessor backed by the stub model and a throwaway cache directory."""
    monkeypatch.setenv("MODEL_CACHE_DIR", str(tmp_path))
    from scorer_processor import ScorerProcessor

    return ScorerProcessor()


@pytest.fixture(autouse=True)
def resolves_publicly(monkeypatch):
    """Answer every hostname with a public address.

    assert_fetchable resolves the hosts it is asked about, and no test should
    depend on DNS. Tests covering rejected addresses override this.
    """
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (PUBLIC_ADDRESS, 0),
            )
        ],
    )


@pytest.fixture
def resolves_to(monkeypatch):
    """Point every hostname at a chosen address."""

    def _resolve_to(address):
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *args, **kwargs: [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    (address, 0),
                )
            ],
        )

    return _resolve_to


@pytest.fixture
def queue_manager(monkeypatch):
    """A QueueManager backed by an in-process Redis, polling without delay.

    Every QueueManager built while the test runs shares one store, so a service
    endpoint can construct its own and still see what the test published. Time
    is stubbed out because polling an empty queue would otherwise sleep.
    """
    from util import queue_util
    from util.queue_util import QueueManager

    server = fakeredis.FakeServer()
    monkeypatch.setattr(
        QueueManager,
        "get_redis_client",
        classmethod(
            lambda cls: fakeredis.FakeRedis(server=server, decode_responses=True)
        ),
    )
    monkeypatch.setattr(queue_util.time, "sleep", lambda seconds: None)
    return QueueManager({"queue_name": "scraped_items"})


@pytest.fixture
def scored():
    """Build a queue item shaped the way the scorer leaves it."""

    def _scored(href="https://example.com/harness", score=0.8, job_id="job-1"):
        return {
            "job_id": job_id,
            "relevance_analysis": {
                "keyword": "harness",
                "source_url": "https://example.com/",
                "href_url": href,
                "score": score,
            },
        }

    return _scored
