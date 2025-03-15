"""
Main entry point for the LLM processor.
"""

import os
import argparse
from loguru import logger
from llm_processor import LLMProcessor
from queue_consumer import QueueConsumer
from producer.src.read_queue import read_queue


def main():
    """Initialize and run the LLM processor."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="LLM Processor")
    parser.add_argument("--read-only", action="store_true", help="Only read and display queue contents")
    args = parser.parse_args()

    # Configure Redis connection
    redis_config = {
        "host": os.getenv("REDIS_HOST", "redis"),
        "port": int(os.getenv("REDIS_PORT", 6379)),
        "queue_name": "scraped_items"
    }

    # Initialize Redis connection
    consumer = QueueConsumer(redis_config)

    try:
        if args.read_only:
            # Just read and display queue contents
            logger.info("\nDisplaying processed items:")
            read_queue(
                redis_client=consumer.redis_client,
                queue_name=consumer.processed_queue_name
            )
        else:
            # Full processing mode
            processor = LLMProcessor()
            consumer.process_queue(processor.process_item)
            
            # Display processed items
            logger.info("\nDisplaying processed items:")
            read_queue(
                redis_client=consumer.redis_client,
                queue_name=consumer.processed_queue_name
            )
            
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        consumer.close()


if __name__ == "__main__":
    main() 