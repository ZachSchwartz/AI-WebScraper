"""
Queue manager for handling Redis queue operations.
"""

import json
import time
import os
from typing import Dict, Any, Optional, Callable, List
import redis
from error_util import format_error


class QueueManager:
    """
    Manages connections to message queues for distributing scraped data.
    """

    @classmethod
    def get_redis_config(
        cls, queue_name: str = "scraped_items", wait_time: int = 5
    ) -> Dict[str, Any]:
        """
        Get standard Redis configuration from environment variables.

        Args:
            queue_name: Name of the queue to use
            wait_time: Time to wait between queue checks in seconds

        Returns:
            Dict containing Redis configuration
        """
        return {
            "type": "redis",
            "host": os.environ.get("REDIS_HOST", "redis"),
            "port": int(os.environ.get("REDIS_PORT", "6379")),
            "queue_name": queue_name,
            "wait_time": wait_time,
        }

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the queue manager.

        Args:
            config: Dictionary containing queue configuration
        """
        self.queue_name = config.get("queue_name", "scraped_items")
        self.processed_queue_name = f"{self.queue_name}_processed"
        self.host = config.get("host", "localhost")
        self.port = config.get("port", 6379)
        self.password = config.get("password", "")
        self.batch_size = config.get("batch_size", 10)
        self.redis_client = self.get_redis_client()

        # Initialize connection
        self._connect()

    @classmethod
    def get_redis_client(cls) -> redis.Redis:
        """
        Get a Redis client connection.

        Returns:
            redis.Redis: Configured Redis client

        Raises:
            redis.RedisError: If connection fails
        """
        try:
            # Get Redis connection details from environment variables or use defaults
            host = os.environ.get("REDIS_HOST", "redis")
            port = int(os.environ.get("REDIS_PORT", "6379"))

            client = redis.Redis(host=host, port=port, decode_responses=True)
            client.ping()  # Test connection
            return client
        except redis.RedisError as e:
            format_error("redis_connection_error", str(e))
            raise

    def _connect(self) -> None:
        """Establish connection to Redis."""
        try:
            print(f"Attempting to connect to Redis at {self.host}:{self.port}")
            self.redis_client = self.get_redis_client()
            print(f"Successfully connected to Redis at {self.host}:{self.port}")
        except redis.RedisError as e:
            format_error("redis_connection_error", str(e))
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
            format_error("redis_publish_error", str(e))
            return False

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
            format_error("redis_get_item_error", str(e))
        return None

    def get_batch(self) -> List[Dict[str, Any]]:
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

    def update_item(self, item: Dict[str, Any]) -> bool:
        """
        Update an item in Redis by pushing it to the processed queue.

        Args:
            item: Processed item to update

        Returns:
            True if successful, False otherwise
        """
        try:
            # Push to processed queue
            self.redis_client.lpush(self.processed_queue_name, json.dumps(item))
            print(f"Added item to processed queue '{self.processed_queue_name}'")
            return True
        except Exception as e:
            format_error("redis_update_item_error", str(e))
            return False

    def process_queue(
        self, processor: Callable[[Dict[str, Any]], Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Process items from the queue continuously.

        Args:
            processor: Callback function to process each item. Can be either a standalone function
                      or an instance method (in which case it should be passed as a lambda)

        Returns:
            List of successfully processed items
        """
        print("Starting queue processing")
        processed_count = 0
        iteration_count = 0
        max_iterations = getattr(
            self, "max_iterations", 1000
        )  # Default to 1000 if not set
        processed_items = []

        try:
            while iteration_count < max_iterations:
                items = self.get_batch()
                if items:
                    print(f"Processing batch of {len(items)} items")
                    for item in items:
                        try:
                            # Process the item
                            processed_item = processor(item)

                            if self.update_item(processed_item):
                                processed_count += 1
                                processed_items.append(processed_item)

                        except Exception as e:
                            print(format_error("processing_error", str(e)))
                            # Don't count failed items as processed
                            continue
                else:
                    if processed_count > 0:
                        print(f"Queue empty after processing {processed_count} items")
                        break
                    print("Queue empty, waiting 5 seconds")
                    time.sleep(5)

                iteration_count += 1

            if iteration_count >= max_iterations:
                print(f"Reached maximum iteration limit of {max_iterations}")

        except KeyboardInterrupt:
            print("Stopping queue processing")
        finally:
            self.close()

        return processed_items

    def close(self) -> None:
        """Close connections to Redis."""
        if self.redis_client:
            self.redis_client.close()
            print("Redis connection closed")

    def clear_queues(self) -> bool:
        """
        Clear both the main queue and processed queue.

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.redis_client.delete(self.queue_name)
            self.redis_client.delete(self.processed_queue_name)
            print("Successfully cleared both main and processed queues")
            return True
        except Exception as e:
            print(format_error(str(e)))
            return False