"""
Main entry point for the LLM processor.
"""

import os
import sys
from llm_processor import LLMProcessor
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
from queue_manager import QueueManager


def main() -> None:
    """Initialize and run the LLM processor."""
    # Configure Redis connection
    redis_config = {
        "type": "redis",
        "host": os.getenv("REDIS_HOST", "redis"),
        "port": int(os.getenv("REDIS_PORT", "6379")),  # Convert string to int
        "queue_name": "scraped_items",
    }

    # Initialize Redis connection
    queue_manager = QueueManager(redis_config)

    processor = LLMProcessor()
    queue_manager.process_queue(processor.process_item)

    # Display processed items
    print("\nDisplaying processed items:")
    queue_manager.read_queue(queue_manager.processed_queue_name)


if __name__ == "__main__":
    main()
