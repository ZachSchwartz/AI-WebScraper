"""
LLM processor using flan-t5-large for text analysis and relevance scoring.
"""

from typing import Dict, Any, Tuple
import torch
from transformers import AutoTokenizer, T5ForConditionalGeneration
from loguru import logger


class LLMProcessor:
    """Processes text content using flan-t5-large model."""

    def __init__(self):
        """Initialize the LLM processor with flan-t5-large."""
        self.model_name = "google/flan-t5-large"
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Using device: {self.device}")
        
        # Load model and tokenizer
        logger.info("Loading flan-t5-large model...")
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self.model = T5ForConditionalGeneration.from_pretrained(
            self.model_name
        ).to(self.device)
        logger.info("Model loaded successfully")

    def generate_relevance_score(self, text: str, keyword: str) -> Tuple[float, str]:
        """
        Generate a relevance score between 0 and 1 for the text relative to the keyword.

        Args:
            text: Text to analyze
            keyword: Keyword to compare against

        Returns:
            Tuple of (score, explanation)
        """
        prompt = (
            f"Rate the relevance of the following text to the keyword '{keyword}' "
            f"on a scale from 0 to 1, where 0 means completely irrelevant and 1 means highly relevant. "
            f"First provide the numerical score, then explain why.\n\nText: {text}"
        )

        # Tokenize and generate
        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=512,
            padding=True
        ).to(self.device)

        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_length=150,
                num_beams=4,
                temperature=0.7,
                top_k=50,
                top_p=0.95,
                do_sample=True,
                no_repeat_ngram_size=2
            )

        # Parse the response
        response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        try:
            # Try to extract the score from the beginning of the response
            parts = response.split(maxsplit=1)
            score = float(parts[0])
            explanation = parts[1] if len(parts) > 1 else ""
            
            # Ensure score is between 0 and 1
            score = max(0.0, min(1.0, score))
        except (ValueError, IndexError):
            # If we can't parse a score, default to 0.5 and keep the full response
            score = 0.5
            explanation = response

        return score, explanation

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
            keyword = item.get("keyword", "")
            if not keyword:
                logger.warning("No keyword found in item, skipping relevance scoring")
                return item

            # Collect all relevant text for scoring
            text_parts = []
            
            # Add URL text
            if item.get("text"):
                text_parts.append(f"Link text: {item['text']}")
            if item.get("title"):
                text_parts.append(f"Link title: {item['title']}")
            if item.get("href"):
                text_parts.append(f"URL: {item['href']}")

            # Add context
            if item.get("context", {}).get("previous_text"):
                text_parts.append(f"Previous context: {item['context']['previous_text']}")
            if item.get("context", {}).get("next_text"):
                text_parts.append(f"Following context: {item['context']['next_text']}")

            # Add metadata if available
            if item.get("metadata", {}).get("description"):
                text_parts.append(f"Description: {item['metadata']['description']}")

            # Combine all text for analysis
            combined_text = "\n".join(text_parts)

            # Generate relevance score
            score, explanation = self.generate_relevance_score(combined_text, keyword)

            # Add results to item
            processed_item = item.copy()
            processed_item["relevance_analysis"] = {
                "model_name": self.model_name,
                "keyword": keyword,
                "score": score,
                "explanation": explanation,
                "analyzed_text": combined_text
            }

            logger.info(f"Generated relevance score {score:.2f} for URL: {item.get('href', 'unknown')}")
            return processed_item

        except Exception as e:
            logger.error(f"Error processing item: {str(e)}")
            return item  # Return original item if processing fails 