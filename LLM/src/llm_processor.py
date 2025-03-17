"""
Relevance processor using sentence transformers for fast text analysis and relevance scoring
with improved caching to prevent repeated downloads.
"""

from typing import Dict, Any, Tuple, List
from urllib.parse import urlparse
import os
import hashlib
import re
import torch

import numpy as np



from sentence_transformers import SentenceTransformer, util




class LLMProcessor:
    """Processes text content using sentence transformers with proper caching."""

    def __init__(self):
        """
        Initialize the relevance processor with a sentence transformer model.
        """
        # Using a small, fast sentence transformer model
        # all-MiniLM-L6-v2 is very fast and has good performance for semantic similarity
        self.model_name = "all-MiniLM-L6-v2"
        # Use a persistent volume mount path for model caching
        self.cache_dir = os.path.abspath("/app/model_cache")
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Using device: {self.device}")

        # Create cache directory if it doesn't exist
        os.makedirs(self.cache_dir, exist_ok=True)

        # Create a directory for caching embeddings
        self.embeddings_cache_dir = os.path.join(self.cache_dir, "embeddings_cache")
        os.makedirs(self.embeddings_cache_dir, exist_ok=True)

        # Load the model
        print(f"Loading sentence transformer model: {self.model_name}")
        self.model = SentenceTransformer(self.model_name, cache_folder=self.cache_dir)
        self.model.to(self.device)
        print("Model loaded successfully")

        # Dictionary to cache embeddings in memory
        self.embedding_cache = {}

    def _get_embedding_key(self, text: str) -> str:
        """Generate a cache key for text embedding."""
        return hashlib.md5(text.encode()).hexdigest()

    def _get_embedding(self, text: str) -> np.ndarray:
        """Get embedding for text with caching."""
        # Check in-memory cache first
        embedding_key = self._get_embedding_key(text)
        if embedding_key in self.embedding_cache:
            return self.embedding_cache[embedding_key]

        # Check file cache
        embedding_file = os.path.join(self.embeddings_cache_dir, f"{embedding_key}.npy")
        if os.path.exists(embedding_file):
            try:
                embedding = np.load(embedding_file)
                # Store in memory cache
                self.embedding_cache[embedding_key] = embedding
                return embedding
            except Exception as e:
                print(f"Error loading embedding from cache: {str(e)}")

        # Generate new embedding
        embedding = self.model.encode(text, convert_to_numpy=True)

        # Save to file cache
        try:
            np.save(embedding_file, embedding)
        except Exception as e:
            print(f"Error saving embedding to cache: {str(e)}")

        # Store in memory cache
        self.embedding_cache[embedding_key] = embedding
        return embedding

    def generate_relevance_score(self, text: str, keyword: str) -> Tuple[float, str]:
        """
        Generate a relevance score between 0 and 1 for the text relative to the keyword.
        Uses semantic analysis with sentence transformers and intelligent scoring.
        Provides nuanced scoring to better rank links by relevance.

        Args:
            text: Text to analyze
            keyword: Keyword to compare against

        Returns:
            Tuple of (score, explanation)
        """
        # Convert to lowercase for case-insensitive matching
        text_lower = text.lower()
        keyword_lower = keyword.lower()

        # 1. Exact match bonus (highest weight)
        exact_match = 1.0 if keyword_lower in text_lower else 0.0

        # 2. Semantic similarity using sentence transformer
        # Get embeddings for text and keyword
        text_embedding = self._get_embedding(text)
        keyword_embedding = self._get_embedding(keyword)

        # Calculate semantic similarity
        semantic_sim = util.cos_sim(text_embedding, keyword_embedding).item()

        # Normalize semantic similarity to 0-1 range with moderate polarization
        # Using a gentler sigmoid curve (steepness of 4)
        semantic_score = 1 / (1 + np.exp(-4 * semantic_sim))

        # 3. Context analysis with increased weight for exact matches
        context_score = 0.0
        if exact_match > 0:
            # If we have an exact match, analyze the surrounding context
            text_parts = text_lower.split()
            for i, word in enumerate(text_parts):
                if word == keyword_lower:
                    # Get context window
                    start_idx = max(0, i - 3)
                    end_idx = min(len(text_parts), i + 4)
                    context_words = text_parts[start_idx:end_idx]

                    # Create context embedding
                    context_text = " ".join(context_words)
                    context_embedding = self._get_embedding(context_text)

                    # Calculate context relevance with moderate curve
                    context_sim = util.cos_sim(
                        context_embedding, keyword_embedding
                    ).item()
                    context_score = 1 / (1 + np.exp(-4 * context_sim))

        # Combine scores with balanced weighting
        # Exact match (0.4), semantic similarity (0.4), context (0.2)
        score = 0.4 * exact_match + 0.4 * semantic_score + 0.2 * context_score

        # Apply a moderate sigmoid transformation to maintain some polarization
        # while allowing for nuanced scores
        score = 1 / (1 + np.exp(-6 * (score - 0.5)))

        # Add soft thresholds to maintain some nuance while still filtering
        # very low relevance content
        if score < 0.2:
            score = 0.0
        elif score > 0.9:
            score = 1.0

        return score

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract potential keywords from text for additional context."""
        # Simple keyword extraction based on capitalized words and phrases
        # This helps provide additional context for relevance scoring
        words = re.findall(r"\b[A-Z][a-zA-Z]*\b", text)
        return list(set(words))[:5]  # Return up to 5 unique keywords

    def _parse_url(self, url: str) -> List[str]:
        """
        Parse a URL into meaningful components.

        Args:
            url: The URL to parse

        Returns:
            List of meaningful URL components
        """
        try:
            parsed = urlparse(url)
            components = []

            # Add domain parts
            if parsed.netloc:
                domain_parts = parsed.netloc.split(".")
                components.extend(domain_parts)

            # Add path parts, filtering out empty strings
            if parsed.path:
                path_parts = [part for part in parsed.path.split("/") if part]
                components.extend(path_parts)

            return components
        except Exception as e:
            print(f"Error parsing URL {url}: {str(e)}")
            return [url]  # Fallback to original URL if parsing fails

    def process_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a queue item and generate relevance scores.

        Args:
            item: Dictionary containing scraped data

        Returns:
            Dictionary containing original data and processing results
        """
        try:
            # Get the keyword and pre-processed text
            keyword = item.get("keyword", "").lower()
            processed_text = item.get("processed_text", "")

            # Generate relevance score
            score = self.generate_relevance_score(processed_text, keyword)

            # Extract potential keywords for additional context
            extracted_keywords = self._extract_keywords(processed_text)

            # Add results to item
            processed_item = item.copy()
            processed_item["relevance_analysis"] = {
                "model_name": self.model_name,
                "keyword": keyword,
                "score": score,
                "extracted_keywords": extracted_keywords,
                "source_url": item.get("source_url"),  # Add source URL for reference
                "metadata_used": bool(
                    item.get("metadata")
                ),  # Track if metadata was used
                "context_used": bool(item.get("context")),  # Track if context was used
            }

            print(
                f"Generated relevance score {score:.2f} for URL: {item.get('href', 'unknown')}"
            )
            return processed_item

        except Exception as e:
            print(f"Error processing item: {str(e)}")
            return item  # Return original item if processing fails
