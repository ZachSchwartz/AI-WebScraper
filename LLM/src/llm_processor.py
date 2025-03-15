"""
LLM processor for analyzing scraped content.
"""

from typing import Dict, Any, List
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from loguru import logger


class LLMProcessor:
    """Processes text content using Hugging Face models."""

    def __init__(self, model_name: str = "distilbert-base-uncased"):
        """
        Initialize the LLM processor.

        Args:
            model_name: Name of the Hugging Face model to use
        """
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Using device: {self.device}")
        
        # Load model and tokenizer
        logger.info(f"Loading model: {model_name}")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            model_name
        ).to(self.device)
        logger.info("Model loaded successfully")

    def process_text(self, text: str) -> Dict[str, Any]:
        """
        Process a single text input.

        Args:
            text: Text to process

        Returns:
            Dictionary containing processing results
        """
        # Tokenize and prepare input
        inputs = self.tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=512,
            padding=True
        ).to(self.device)

        # Get model output
        with torch.no_grad():
            outputs = self.model(**inputs)
            logits = outputs.logits
            predictions = torch.softmax(logits, dim=1)

        # Convert to Python types for JSON serialization
        result = {
            "predictions": predictions[0].tolist(),
            "label": predictions[0].argmax().item(),
            "confidence": predictions[0].max().item()
        }

        return result

    def process_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a queue item.

        Args:
            item: Dictionary containing scraped data

        Returns:
            Dictionary containing original data and processing results
        """
        try:
            # Extract text content from item
            texts = []
            if item.get("text"):
                texts.append(item["text"])
            if item.get("context", {}).get("previous_text"):
                texts.append(item["context"]["previous_text"])
            if item.get("context", {}).get("next_text"):
                texts.append(item["context"]["next_text"])

            # Process each text
            results = []
            for text in texts:
                if text:
                    result = self.process_text(text)
                    results.append(result)

            # Add results to item
            processed_item = item.copy()
            processed_item["llm_analysis"] = {
                "model_name": self.model_name,
                "results": results
            }

            return processed_item
        except Exception as e:
            logger.error(f"Error processing item: {str(e)}")
            return item  # Return original item if processing fails 