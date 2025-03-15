"""
Queue consumer for processing items from Redis.
"""

import json
import time
from typing import Dict, Any, Optional, Callable
import redis
from loguru import logger


class QueueConsumer:
    """Consumes items from Redis queue for processing."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the queue consumer.

        Args:
            config: Dictionary containing queue configuration
        """
        self.queue_name = config.get("queue_name", "scraped_items")
        self.host = config.get("host", "redis")
        self.port = config.get("port", 6379)
        self.password = config.get("password", "")
        self.batch_size = config.get("batch_size", 10)
        self.wait_time = config.get("wait_time", 5)  # seconds to wait if queue is empty
        self.redis_client = None

        # Initialize connection
        self._connect()

    def _connect(self) -> None:
        """Establish connection to Redis."""
        try:
            logger.info(f"Connecting to Redis at {self.host}:{self.port}")
            self.redis_client = redis.Redis(
                host=self.host,
                port=self.port,
                password=self.password if self.password else None,
                decode_responses=True  # Automatically decode to strings
            )
            # Test connection
            self.redis_client.ping()
            logger.info("Successfully connected to Redis")
        except redis.RedisError as e:
            logger.error(f"Failed to connect to Redis: {str(e)}")
            raise

    def get_item(self) -> Optional[Dict[str, Any]]:
        """
        Get a single item from the queue.

        Returns:
            Dictionary containing the item data or None if queue is empty
        """
        try:
            # Pop item from the right of the list (FIFO order)
            item_json = self.redis_client.rpop(self.queue_name)
            if item_json:
                return json.loads(item_json)
        except Exception as e:
            logger.error(f"Error getting item from queue: {str(e)}")
        return None

    def get_batch(self) -> list[Dict[str, Any]]:
        """
        Get a batch of items from the queue.

        Returns:
            List of dictionaries containing item data
        """
        items = []
        for _ in range(self.batch_size):
            item = self.get_item()
            if item:
                items.append(item)
            else:
                break
        return items

    def process_queue(self, processor: Callable[[Dict[str, Any]], None]) -> None:
        """
        Process items from the queue continuously.

        Args:
            processor: Callback function to process each item
        """
        logger.info("Starting queue processing")
        try:
            while True:
                items = self.get_batch()
                if items:
                    logger.info(f"Processing batch of {len(items)} items")
                    for item in items:
                        try:
                            processor(item)
                        except Exception as e:
                            logger.error(f"Error processing item: {str(e)}")
                else:
                    logger.info(f"Queue empty, waiting {self.wait_time} seconds")
                    time.sleep(self.wait_time)
        except KeyboardInterrupt:
            logger.info("Stopping queue processing")
        finally:
            self.close()

    def close(self) -> None:
        """Close connections to Redis."""
        if self.redis_client:
            self.redis_client.close()
            logger.info("Redis connection closed") 