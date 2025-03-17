"""
Relevance processor using sentence transformers for fast text analysis and relevance scoring
with improved caching to prevent repeated downloads.
"""

from typing import Dict, Any, Tuple, Optional, List
import torch
import numpy as np
from sentence_transformers import SentenceTransformer, util
import os
import hashlib
import json
import re
from urllib.parse import urlparse

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
        
        # Normalize semantic similarity to 0-1 range
        # Use a sigmoid-like transformation to make it more discriminating
        semantic_score = 1 / (1 + np.exp(-5 * semantic_sim))
        
        # 3. Context analysis
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
                    
                    # Calculate context relevance
                    context_sim = util.cos_sim(context_embedding, keyword_embedding).item()
                    context_score = 1 / (1 + np.exp(-5 * context_sim))
        
        # Combine scores with intelligent weighting
        # Exact match gets highest weight (0.4), semantic similarity (0.4), context (0.2)
        score = (0.6 * exact_match + 
                0.4 * semantic_score + 
                0.2 * context_score)
        
        # Apply a sigmoid transformation to make the final score more discriminating
        score = 1 / (1 + np.exp(-5 * (score - 0.5)))
        
        # Generate explanation based on score
        if score > 0.8:
            explanation = f"Very high relevance ({score:.2f}): The content is strongly related to '{keyword}'."
        elif score > 0.6:
            explanation = f"High relevance ({score:.2f}): The content is clearly related to '{keyword}'."
        elif score > 0.4:
            explanation = f"Moderate relevance ({score:.2f}): The content has some relation to '{keyword}'."
        elif score > 0.2:
            explanation = f"Low relevance ({score:.2f}): The content is only slightly related to '{keyword}'."
        else:
            explanation = f"Very low relevance ({score:.2f}): The content appears unrelated to '{keyword}'."
        
        return score, explanation
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract potential keywords from text for additional context."""
        # Simple keyword extraction based on capitalized words and phrases
        # This helps provide additional context for relevance scoring
        words = re.findall(r'\b[A-Z][a-zA-Z]*\b', text)
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
                domain_parts = parsed.netloc.split('.')
                components.extend(domain_parts)
            
            # Add path parts, filtering out empty strings
            if parsed.path:
                path_parts = [part for part in parsed.path.split('/') if part]
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
            # Get the keyword from the item
            keyword = item.get("keyword", "").lower()

            # Collect all relevant text for scoring
            text_parts = []
            
            # Add meaningful text content first
            if item.get("text"):
                text = item['text'].strip()
                if text and text.lower() != "more information...":  # Skip generic link text
                    text_parts.append(text)
                    
            if item.get("title"):
                title = item['title'].strip()
                if title:
                    text_parts.append(title)
            
            # Add aria-label if it exists and is meaningful
            if item.get("aria-label"):
                aria = item['aria-label'].strip()
                if aria and aria.lower() != "more information...":  # Skip generic aria labels
                    text_parts.append(aria)
            
            # Add rel attribute if it provides meaningful context
            if item.get("rel"):
                rel = item['rel']
                if isinstance(rel, list):
                    rel = " ".join(rel)
                if rel and rel.lower() not in ["nofollow", "noopener"]:  # Skip common generic rel values
                    text_parts.append(rel)
            
            # Add metadata information
            if item.get("metadata"):
                metadata = item["metadata"]
                if metadata.get("title"):
                    page_title = metadata["title"].strip()
                    if page_title:
                        text_parts.append(page_title)
                
                if metadata.get("description"):
                    desc = metadata['description'].strip()
                    if desc and len(desc) > 10:  # Only add if it's not too short
                        if len(desc) > 300:  # Truncate very long descriptions
                            desc = desc[:300] + "..."
                        text_parts.append(desc)
            
            # Process URLs and domains efficiently
            processed_domains = set()  # Track processed domains to avoid duplicates
            
            def process_url(url_str: str) -> List[str]:
                """Process a URL and return meaningful components."""
                if not url_str:
                    return []
                
                parsed = urlparse(url_str)
                components = []
                
                # Process domain
                if parsed.netloc:
                    domain = parsed.netloc.lower()
                    # Remove common prefixes and suffixes
                    domain = domain.replace('www.', '').replace('.com', '').replace('.org', '')
                    if domain and domain not in processed_domains:
                        components.append(domain)
                        processed_domains.add(domain)
                
                # Process path
                if parsed.path:
                    path = parsed.path.strip('/')
                    if path:
                        # Split path into meaningful words, handling both slashes and hyphens
                        path_words = [word for word in re.split(r'[/-]', path) if word]
                        # Filter out common generic terms
                        path_words = [word for word in path_words 
                                    if word.lower() not in {'index', 'home', 'page', 'default'}]
                        components.extend(path_words)
                
                return components
            
            # Process source URL
            if item.get("source_url"):
                text_parts.extend(process_url(item["source_url"]))
            
            # Process target URL
            if item.get("href"):
                text_parts.extend(process_url(item["href"]))
            
            # Add surrounding context if available
            if item.get("context"):
                context = item["context"]
                if context.get("previous_text"):
                    text_parts.append(context["previous_text"])
                if context.get("next_text"):
                    text_parts.append(context["next_text"])
                if context.get("heading_hierarchy"):
                    text_parts.extend(context["heading_hierarchy"])

            # Remove duplicates while preserving order
            text_parts = list(dict.fromkeys(text_parts))
            
            # Combine all text for analysis
            combined_text = " ".join(text_parts)
            print(f"Combined text: {combined_text}")
            
            # Generate relevance score
            score, explanation = self.generate_relevance_score(combined_text, keyword)
            
            # Extract potential keywords for additional context
            extracted_keywords = self._extract_keywords(combined_text)

            # Add results to item
            processed_item = item.copy()
            processed_item["relevance_analysis"] = {
                "model_name": self.model_name,
                "keyword": keyword,
                "score": score,
                "explanation": explanation,
                "extracted_keywords": extracted_keywords,
                "text_parts_used": text_parts,  # Add this for debugging
                "source_url": item.get("source_url"),  # Add source URL for reference
                "metadata_used": bool(item.get("metadata")),  # Track if metadata was used
                "context_used": bool(item.get("context"))  # Track if context was used
            }

            print(f"Generated relevance score {score:.2f} for URL: {item.get('href', 'unknown')}")
            return processed_item

        except Exception as e:
            print(f"Error processing item: {str(e)}")
            return item  # Return original item if processing fails
