"""
Shared test fixtures.

The scorer service imports torch and sentence-transformers at module level, which
together weigh over a gigabyte and download a model on first use. The tests
substitute a deterministic stand-in instead: embeddings are hashed bag-of-words
vectors, so cosine similarity still rises with shared vocabulary and the scoring
logic can be exercised without the real model.
"""

# pylint: disable=missing-function-docstring,unused-argument,import-outside-toplevel

import sys
import types
import zlib
import numpy as np
import pytest

EMBEDDING_DIM = 256


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

    def encode(self, text: str, convert_to_numpy: bool = True) -> np.ndarray:
        self.encoded.append(text)
        return _encode(text)


def _install_stubs() -> None:
    """Register stub modules before scorer_processor is imported."""
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    sys.modules.setdefault("torch", torch)

    sentence_transformers = types.ModuleType("sentence_transformers")
    sentence_transformers.SentenceTransformer = FakeSentenceTransformer
    sentence_transformers.util = types.SimpleNamespace(cos_sim=_cos_sim)
    sys.modules.setdefault("sentence_transformers", sentence_transformers)


_install_stubs()


@pytest.fixture
def scorer_processor(tmp_path, monkeypatch):
    """A ScorerProcessor backed by the stub model and a throwaway cache directory."""
    monkeypatch.setenv("MODEL_CACHE_DIR", str(tmp_path))
    from scorer_processor import ScorerProcessor

    return ScorerProcessor()
