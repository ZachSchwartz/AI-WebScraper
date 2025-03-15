"""
Main entry point for the LLM processor.
"""

import argparse
from queue_consumer import QueueConsumer
from llm_processor import LLMProcessor
from loguru import logger


def main(model_name: str):
    """
    Main entry point for the LLM processor.

    Args:
        model_name: Name of the Hugging Face model to use
    """
    # Initialize queue consumer
    queue_config = {
        "host": "redis",
        "port": 6379,
        "queue_name": "scraped_items",
        "batch_size": 10,
        "wait_time": 5
    }
    consumer = QueueConsumer(queue_config)
    logger.info("Queue consumer initialized")

    # Initialize LLM processor
    processor = LLMProcessor(model_name)
    logger.info("LLM processor initialized")

    # Start processing queue
    logger.info("Starting queue processing")
    consumer.process_queue(processor.process_item)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM processor for scraped content")
    parser.add_argument(
        "--model",
        default="distilbert-base-uncased",
        help="Name of the Hugging Face model to use"
    )
    
    args = parser.parse_args()
    main(args.model) 