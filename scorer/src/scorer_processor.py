"""
Relevance processor using sentence transformers for fast text analysis and relevance scoring
with improved caching to prevent repeated downloads.
"""

import os
import hashlib
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
import torch
import numpy as np
from sentence_transformers import SentenceTransformer, util

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONTEXT_WINDOW = 3
MODEL_NAME = "all-MiniLM-L6-v2"


def _sigmoid(value: float, steepness: float, midpoint: float = 0.0) -> float:
    """Squash a similarity onto 0-1, sharpening the gap around the midpoint."""
    return float(1 / (1 + np.exp(-steepness * (value - midpoint))))


def context_windows(text_lower: str, keyword_lower: str) -> List[str]:
    """The words surrounding each standalone occurrence of the keyword.

    A keyword that only appears inside a longer word has no window here, so a
    page that mentions it in passing scores on similarity alone.
    """
    words = text_lower.split()
    return [
        " ".join(words[max(0, index - CONTEXT_WINDOW) : index + CONTEXT_WINDOW + 1])
        for index, word in enumerate(words)
        if word == keyword_lower
    ]


class ScorerProcessor:
    """Processes text content using sentence transformers with proper caching."""

    def __init__(self) -> None:
        """Load the sentence transformer, caching it on a persistent volume.

        The cache directory holds both the downloaded model and the embeddings
        it produces, so a restart neither downloads nor re-encodes.
        """
        self.cache_dir = os.path.abspath(
            os.environ.get("MODEL_CACHE_DIR", "/app/model_cache")
        )
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("Using device: %s", self.device)

        self.embeddings_cache_dir = os.path.join(self.cache_dir, "embeddings_cache")
        os.makedirs(self.embeddings_cache_dir, exist_ok=True)

        logger.info("Loading sentence transformer model: %s", MODEL_NAME)
        self.model = SentenceTransformer(MODEL_NAME, cache_folder=self.cache_dir)
        self.model.to(self.device)
        logger.info("Model loaded successfully")

        self.embedding_cache: Dict[str, np.ndarray] = {}

    def _get_embedding_key(self, text: str) -> str:
        """Generate a cache key for text embedding."""
        return hashlib.md5(text.encode()).hexdigest()

    def _cache_file(self, key: str) -> str:
        """Where an embedding for this key is kept between runs."""
        return os.path.join(self.embeddings_cache_dir, f"{key}.npy")

    def _cached_embedding(self, key: str) -> Optional[np.ndarray]:
        """Read an embedding from memory or disk, or None if neither holds it."""
        if key in self.embedding_cache:
            return self.embedding_cache[key]

        embedding_file = self._cache_file(key)
        if os.path.exists(embedding_file):
            try:
                embedding = np.load(embedding_file)
                self.embedding_cache[key] = embedding
                return embedding
            except (OSError, ValueError):
                logger.warning(
                    "Ignoring unreadable cached embedding %s", embedding_file
                )

        return None

    def _store_embedding(self, key: str, embedding: np.ndarray) -> None:
        """Keep an embedding for the rest of this run and for the next one."""
        try:
            np.save(self._cache_file(key), embedding)
        except OSError:
            logger.warning("Could not cache an embedding to %s", self._cache_file(key))

        self.embedding_cache[key] = embedding

    def _get_embeddings(self, texts: List[str]) -> List[np.ndarray]:
        """Embed every text, encoding the ones no cache holds in one pass.

        The model batches natively, so the texts a single score needs cost one
        call rather than one call each. Duplicates within the batch are encoded
        once, which matters because a keyword repeats for every link on a page.
        """
        keys = [self._get_embedding_key(text) for text in texts]
        embeddings: Dict[str, np.ndarray] = {}
        missing: Dict[str, str] = {}

        for key, text in zip(keys, texts):
            if key in embeddings or key in missing:
                continue
            cached = self._cached_embedding(key)
            if cached is None:
                missing[key] = text
            else:
                embeddings[key] = cached

        if missing:
            encoded = self.model.encode(list(missing.values()), convert_to_numpy=True)
            for key, embedding in zip(missing, encoded):
                self._store_embedding(key, embedding)
                embeddings[key] = embedding

        return [embeddings[key] for key in keys]

    def generate_relevance_score(self, text: str, keyword: str) -> float:
        """Score how relevant the text is to the keyword, between 0 and 1.

        An exact match carries the most weight, then similarity over the whole
        text, then the best of the keyword's context windows. The strongest
        context wins, so a link that uses the keyword meaningfully once is not
        diluted by the other places the same page repeats it.

        Args:
            text: Text to analyze
            keyword: Keyword to compare against

        Returns:
            Score between 0 and 1
        """
        text_lower = text.lower()
        keyword_lower = keyword.lower()
        exact_match = 1.0 if keyword_lower in text_lower else 0.0

        contexts = context_windows(text_lower, keyword_lower) if exact_match else []
        embeddings = self._get_embeddings([text, keyword, *contexts])
        keyword_embedding = embeddings[1]

        def similarity(embedding: np.ndarray) -> float:
            return _sigmoid(
                util.cos_sim(embedding, keyword_embedding).item(), steepness=8
            )

        semantic_score = similarity(embeddings[0])
        context_score = max(
            (similarity(embedding) for embedding in embeddings[2:]), default=0.0
        )

        score = 0.5 * exact_match + 0.3 * semantic_score + 0.2 * context_score
        return _sigmoid(score, steepness=10, midpoint=0.6)

    def process_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a queue item and generate relevance scores.

        Args:
            item: Dictionary containing scraped data

        Returns:
            Dictionary containing original data and processing results
        """
        try:
            keyword = item.get("keyword", "").lower()
            processed_text = item.get("processed_text", "")
            score = self.generate_relevance_score(processed_text, keyword)

            source_url = item.get("source_url", "")
            href = urljoin(source_url, item.get("href", ""))

            processed_item = item.copy()
            processed_item["relevance_analysis"] = {
                "keyword": keyword,
                "source_url": source_url,
                "href_url": href,
                "score": score,
            }

            return processed_item

        except Exception:
            logger.exception("Could not score an item; leaving it unscored")
            return item
