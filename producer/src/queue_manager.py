"""
Queue manager for the producer component.
Handles publishing scraped items to a message queue.
"""

import json
from typing import Dict, Any
import redis


class QueueManager:
    """
    Manages connections to message queues for distributing scraped data.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the queue manager.

        Args:
            config: Dictionary containing queue configuration
        """
        self.queue_type = config.get("type", "redis").lower()
        self.queue_name = config.get("queue_name", "scraped_items")
        self.host = config.get("host", "localhost")
        self.port = config.get("port", 6379)
        self.password = config.get("password", "")
        self.redis_client = None

        # Initialize connection
        self._connect()

    def _connect(self) -> None:
        """Establish connection to Redis."""
        try:
            self.redis_client = redis.Redis(
                host=self.host,
                port=self.port,
                password=self.password if self.password else None,
                decode_responses=False,
            )
            # Test connection
            self.redis_client.ping()
            print(f"Connected to Redis at {self.host}:{self.port}")
        except redis.RedisError as e:
            print(f"Failed to connect to Redis: {str(e)}")
            raise

    def publish_item(self, item: Dict[str, Any]) -> bool:
        """
        Publish an item to the queue.

        Args:
            item: Dictionary containing scraped data

        Returns:
            True if successful, False otherwise
        """
        try:
            # Serialize the item to JSON
            message = json.dumps(item)

            # Push to Redis list
            self.redis_client.lpush(self.queue_name, message)
            return True
        except Exception as e:
            print(f"Error publishing item to queue: {str(e)}")
            return False

    def close(self) -> None:
        """Close connections to Redis."""
        if self.redis_client:
            self.redis_client.close()
            print("Redis connection closed")
