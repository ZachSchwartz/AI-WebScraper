"""
LLM processor using flan-t5-large for text analysis and relevance scoring
with improved caching to prevent repeated downloads.
"""

from typing import Dict, Any, Tuple
import torch
from transformers import AutoTokenizer, T5ForConditionalGeneration
import os
import shutil
import re

class LLMProcessor:
    """Processes text content using flan-t5-large model with proper caching."""

    def __init__(self):
        """Initialize the LLM processor with flan-t5-large."""
        self.model_name = "google/flan-t5-large"
        # Use a persistent volume mount path for model caching
        self.cache_dir = os.path.abspath("/app/model_cache")
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Using device: {self.device}")
        
        # Create cache directory if it doesn't exist
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # Check if model is already cached
        model_path = os.path.join(self.cache_dir, "models--google--flan-t5-large")
        if os.path.exists(model_path):
            print(f"Found cached model at: {model_path}")
            self._load_from_cache()
        else:
            print(f"Downloading model to cache: {self.cache_dir}")
            self._download_and_cache()

    def _load_from_cache(self):
        """Load model and tokenizer from cache."""
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_name,
            cache_dir=self.cache_dir,
            local_files_only=True
        )
        
        self.model = T5ForConditionalGeneration.from_pretrained(
            self.model_name,
            cache_dir=self.cache_dir,
            local_files_only=True
        ).to(self.device)
        
        print("Model loaded from cache successfully")

    def _download_and_cache(self):
        """Download and cache the model."""
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_name,
            cache_dir=self.cache_dir,
            local_files_only=False
        )
        
        self.model = T5ForConditionalGeneration.from_pretrained(
            self.model_name,
            cache_dir=self.cache_dir,
            local_files_only=False
        ).to(self.device)
        
        print("Model downloaded and cached successfully")
        print(f"Model cached at: {self.cache_dir}")

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
            f"Task: Rate the relevance of the following text to the keyword '{keyword}'.\n"
            f"Instructions:\n"
            f"1. Provide a score between 0.0 and 1.0\n"
            f"2. Score 0.0 if the text is completely unrelated to the keyword\n"
            f"3. Score 1.0 ONLY if the text is DIRECTLY and STRONGLY related to the keyword\n"
            f"4. Most texts should receive scores between 0.1 and 0.9 based on relevance level\n"
            f"5. Be critical and precise in your scoring\n"
            f"6. Start your response with ONLY the numerical score (e.g., '0.7')\n"
            f"7. After the score, explain your reasoning\n\n"
            f"Text to analyze:\n{text}"
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
                temperature=0.7,  # Increased temperature for more varied outputs
                top_k=50,
                top_p=0.95,
                do_sample=True,
                no_repeat_ngram_size=2
            )

        # Parse the response
        response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        try:
            # Try to extract the score from the beginning of the response
            # Look for numbers that might be scores at the start of the response
            score_match = re.search(r'^(\d*\.?\d+)', response)
            if score_match:
                score = float(score_match.group(1))
                # Get the explanation (everything after the score)
                explanation = response[score_match.end():].strip()
                
                # If explanation starts with a period or colon, remove it
                explanation = re.sub(r'^[\.:\s]+', '', explanation)
                
                # If explanation is empty or just the same as the score, use a default explanation
                if not explanation or explanation.strip() == str(score):
                    explanation = f"The model assigned a relevance score of {score} but did not provide an explanation."
            else:
                # If no score found at start, look for any decimal number in the response
                score_match = re.search(r'(\d+\.\d+)', response)
                if score_match:
                    score = float(score_match.group(1))
                    # Get everything after the score as the explanation
                    score_pos = response.find(score_match.group(1))
                    if score_pos >= 0:
                        explanation = response[score_pos + len(score_match.group(1)):].strip()
                        explanation = re.sub(r'^[\.:\s]+', '', explanation)
                    else:
                        explanation = response
                else:
                    # Look for any number in the response
                    score_match = re.search(r'(\d+)', response)
                    if score_match:
                        score = float(score_match.group(1))
                        # If it's a whole number and > 1, assume it's out of 10
                        if score > 1:
                            score = score / 10
                        # Get everything after the score as the explanation
                        score_pos = response.find(score_match.group(1))
                        if score_pos >= 0:
                            explanation = response[score_pos + len(score_match.group(1)):].strip()
                            explanation = re.sub(r'^[\.:\s]+', '', explanation)
                        else:
                            explanation = response
                    else:
                        # If still no score found, use a heuristic approach
                        if "not relevant" in response.lower() or "unrelated" in response.lower():
                            score = 0.1
                        elif "highly relevant" in response.lower() or "strongly related" in response.lower():
                            score = 0.9
                        else:
                            score = 0.5  # Default to middle score
                        explanation = response
            
            # Ensure score is between 0 and 1
            score = max(0.0, min(1.0, score))
            
            # If no explanation was extracted or explanation is just the score, use the full response
            if not explanation or explanation.strip() == str(score):
                explanation = f"The model assigned a relevance score of {score} based on the analyzed text."
                
            # Log the extracted score and response for debugging
            print(f"Raw response: {response}")
            print(f"Extracted score: {score}")
            print(f"Extracted explanation: {explanation}")
                
        except (ValueError, IndexError) as e:
            # If we can't parse a score, default to 0.5 and keep the full response
            print(f"Warning: Could not parse score from response: {response}")
            print(f"Error: {str(e)}")
            score = 0.5  # Changed default from 0.0 to 0.5
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

            print(f"Generated relevance score {score:.2f} for URL: {item.get('href', 'unknown')} with keyword: {keyword}")
            return processed_item

        except Exception as e:
            print(f"Error processing item: {str(e)}")
            return item  # Return original item if processing fails
