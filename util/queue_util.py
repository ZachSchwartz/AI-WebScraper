"""
Queue manager for handling Redis queue operations.
"""

import json
import logging
import time
import os
from typing import Dict, Any, Optional, Callable, List, cast
import redis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_QUEUE_NAME = "scraped_items"
QUEUE_TTL_SECONDS = 3600


def scoped_queue_name(name: str, job_id: Optional[str]) -> str:
    """Name the key one job's items travel through.

    Every stage drains only the key its own job wrote, so two scrapes running at
    once cannot consume each other's links. A caller with no job to scope to
    keeps the shared key, which is what the command line entry points use.
    """
    return f"{name}:{job_id}" if job_id else name


class QueueManager:
    """
    Manages connections to message queues for distributing scraped data.
    """

    @classmethod
    def get_redis_config(
        cls,
        queue_name: str = DEFAULT_QUEUE_NAME,
        wait_time: int = 5,
        job_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get standard Redis configuration from environment variables.

        Args:
            queue_name: Name of the queue to use
            wait_time: Time to wait between queue checks in seconds
            job_id: Scrape to scope the queue keys to, if any

        Returns:
            Dict containing Redis configuration
        """
        return {
            "type": "redis",
            "host": os.environ.get("REDIS_HOST", "redis"),
            "port": int(os.environ.get("REDIS_PORT", "6379")),
            "queue_name": queue_name,
            "job_id": job_id,
            "wait_time": wait_time,
        }

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the queue manager.

        Args:
            config: Dictionary containing queue configuration
        """
        base_name = config.get("queue_name", DEFAULT_QUEUE_NAME)
        job_id = config.get("job_id")
        self.queue_name = scoped_queue_name(base_name, job_id)
        self.processed_queue_name = scoped_queue_name(f"{base_name}_processed", job_id)
        self.batch_size = config.get("batch_size", 10)
        self.wait_time = config.get("wait_time", 5)
        self.max_idle_polls = config.get("max_idle_polls", 3)
        self.max_iterations = config.get("max_iterations", 1000)
        self.redis_client = self.get_redis_client()

    @classmethod
    def get_redis_client(cls) -> redis.Redis:
        """
        Get a Redis client connection.

        Returns:
            redis.Redis: Configured Redis client

        Raises:
            redis.RedisError: If connection fails
        """
        host = os.environ.get("REDIS_HOST", "redis")
        port = int(os.environ.get("REDIS_PORT", "6379"))

        try:
            client = redis.Redis(host=host, port=port, decode_responses=True)
            client.ping()
            logger.info("Connected to Redis at %s:%s", host, port)
            return client
        except redis.RedisError:
            logger.exception("Could not connect to Redis at %s:%s", host, port)
            raise

    @classmethod
    def check_connection(cls) -> None:
        """Raise if the Redis the queues ride on cannot be reached."""
        client = cls.get_redis_client()
        client.ping()
        client.close()

    def _push(self, queue_name: str, item: Dict[str, Any]) -> bool:
        """Append an item to a queue, keeping the key from outliving its job.

        A scrape that fails partway leaves its items behind, and the key they sit
        on belongs to that job alone. The expiry, refreshed on every push, clears
        an abandoned key instead of leaving it in Redis for good.
        """
        try:
            pipeline = self.redis_client.pipeline()
            pipeline.lpush(queue_name, json.dumps(item))
            pipeline.expire(queue_name, QUEUE_TTL_SECONDS)
            pipeline.execute()
            return True
        except (redis.RedisError, TypeError, ValueError):
            logger.exception("Could not publish an item to %s", queue_name)
            return False

    def publish_item(self, item: Dict[str, Any]) -> bool:
        """
        Publish an item to the queue.

        Args:
            item: Dictionary containing scraped data

        Returns:
            True if successful, False otherwise
        """
        return self._push(self.queue_name, item)

    def get_item(self) -> Optional[Dict[str, Any]]:
        """
        Get a single item from the queue.

        Returns:
            Dictionary containing the item data or None if queue is empty
        """
        try:
            item_json = cast(Optional[str], self.redis_client.rpop(self.queue_name))
            if item_json:
                return json.loads(item_json)
        except (redis.RedisError, ValueError):
            logger.exception("Could not read an item from %s", self.queue_name)
        return None

    def get_batch(self) -> List[Dict[str, Any]]:
        """
        Get a batch of items from the queue.

        Returns:
            List of dictionaries containing item data
        """
        items: List[Dict[str, Any]] = []
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
        return self._push(self.processed_queue_name, item)

    def process_queue(
        self,
        processor: Callable[[Dict[str, Any]], Dict[str, Any]],
        forward: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Drain the queue, handing every item to the processor.

        An item whose processor raises is dropped rather than forwarded, so a
        failure downstream never reports itself upstream as a success.

        Args:
            processor: Callback function to process each item. Accepts either a
                       standalone function or a bound method.
            forward: Whether a processed item is republished to the processed
                     queue. The last stage of the pipeline stores its items
                     rather than passing them on, and would otherwise fill a
                     queue nothing ever reads.

        Returns:
            List of successfully processed items
        """
        logger.info("Draining queue %s", self.queue_name)
        processed_items: List[Dict[str, Any]] = []
        idle_polls = 0

        try:
            for _ in range(self.max_iterations):
                items = self.get_batch()
                if not items:
                    if processed_items:
                        break
                    idle_polls += 1
                    if idle_polls >= self.max_idle_polls:
                        logger.info("Queue %s stayed empty", self.queue_name)
                        break
                    time.sleep(self.wait_time)
                    continue

                idle_polls = 0
                for item in items:
                    try:
                        processed_item = processor(item)
                    except Exception:
                        logger.exception("Dropping an item the processor rejected")
                        continue

                    if not forward or self.update_item(processed_item):
                        processed_items.append(processed_item)
            else:
                logger.warning("Stopped at the %d iteration cap", self.max_iterations)

        except KeyboardInterrupt:
            logger.info("Stopping queue processing")

        logger.info("Processed %d items from %s", len(processed_items), self.queue_name)
        return processed_items

    def close(self) -> None:
        """Close connections to Redis."""
        if self.redis_client:
            self.redis_client.close()
            logger.info("Redis connection closed")
