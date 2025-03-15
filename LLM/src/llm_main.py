"""
Main entry point for the LLM processor.
"""

import os
import sys
import argparse
from loguru import logger
from llm_processor import LLMProcessor
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from queue_manager import QueueManager

def main():
    """Initialize and run the LLM processor."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="LLM Processor")
    parser.add_argument("--read-only", action="store_true", help="Only read and display queue contents")
    args = parser.parse_args()

    # Configure Redis connection
    redis_config = {
        "type": "redis",
        "host": os.getenv("REDIS_HOST", "redis"),
        "port": int(os.getenv("REDIS_PORT", 6379)),
        "queue_name": "scraped_items"
    }

    # Initialize Redis connection
    queue_manager = QueueManager(redis_config)

    try:
        if args.read_only:
            # Just read and display queue contents
            logger.info("\nDisplaying processed items:")
            queue_manager.read_queue(queue_manager.processed_queue_name)
        else:
            # Full processing mode
            processor = LLMProcessor()
            queue_manager.process_queue(processor.process_item)
            
            # Display processed items
            logger.info("\nDisplaying processed items:")
            queue_manager.read_queue(queue_manager.processed_queue_name)
            
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        queue_manager.close()


if __name__ == "__main__":
    main() 