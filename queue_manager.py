"""
Queue manager for handling Redis queue operations.
"""

import json
import time
from typing import Dict, Any, Optional, Callable, List
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
        self.processed_queue_name = f"{self.queue_name}_processed"
        self.host = config.get("host", "localhost")
        self.port = config.get("port", 6379)
        self.password = config.get("password", "")
        self.batch_size = config.get("batch_size", 10)
        self.wait_time = config.get("wait_time", 5)
        self.redis_client = None

        # Initialize connection
        self._connect()

    def _connect(self) -> None:
        """Establish connection to Redis."""
        try:
            print(f"Attempting to connect to Redis at {self.host}:{self.port}")
            self.redis_client = redis.Redis(
                host=self.host,
                port=self.port,
                password=self.password if self.password else None,
                decode_responses=True,
            )
            # Test connection
            self.redis_client.ping()
            print(f"Successfully connected to Redis at {self.host}:{self.port}")
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
            print(f"Error getting item from queue: {str(e)}")
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
            return True
        except Exception as e:
            print(f"Error updating item in Redis: {str(e)}")
            return False

    def read_processed_queue(self) -> List[Dict[str, Any]]:
        """
        Read all items from the processed queue without removing them.
        Prints complete details of the first 5 items in a readable format.

        Returns:
            List of processed items
        """
        try:
            # Get all items from the processed queue
            items = []
            queue_length = self.redis_client.llen(self.processed_queue_name)
            
            print(f"\nFound {queue_length} items in processed queue")
            print("=" * 80)
            
            # Only display first 5 items
            display_count = min(5, queue_length)
            
            for i in range(queue_length):
                item_json = self.redis_client.lindex(self.processed_queue_name, i)
                if item_json:
                    item = json.loads(item_json)
                    items.append(item)
                    
                    # Print complete item details for first 5 items
                    if i < display_count:
                        print(f"\nItem {i + 1}/{display_count}:")
                        print("=" * 80)
                        
                        # Print the entire item in a formatted way
                        def format_dict(d: Dict[str, Any], indent: int = 0) -> None:
                            for key, value in d.items():
                                indent_str = "  " * indent
                                if isinstance(value, dict):
                                    print(f"{indent_str}{key}:")
                                    format_dict(value, indent + 1)
                                elif isinstance(value, list):
                                    print(f"{indent_str}{key}:")
                                    for item in value:
                                        if isinstance(item, dict):
                                            format_dict(item, indent + 1)
                                        else:
                                            print(f"{indent_str}  - {item}")
                                else:
                                    print(f"{indent_str}{key}: {value}")
                        
                        format_dict(item)
                        print("=" * 80)
            
            if queue_length > 5:
                print(f"\nNote: Displayed first {display_count} items out of {queue_length} total items")
            
            return items
        except Exception as e:
            print(f"Error reading processed queue: {str(e)}")
            return []

    def process_queue(self, processor: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
        """
        Process items from the queue continuously.

        Args:
            processor: Callback function to process each item
        """
        print("Starting queue processing")
        processed_count = 0
        
        try:
            while True:
                items = self.get_batch()
                if items:
                    print(f"Processing batch of {len(items)} items")
                    for item in items:
                        try:
                            # Process the item
                            processed_item = processor(item)
                            # Update the item in Redis
                            if self.update_item(processed_item):
                                processed_count += 1
                        except Exception as e:
                            print(f"Error processing item: {str(e)}")
                else:
                    if processed_count > 0:
                        print(f"Queue empty after processing {processed_count} items")
                        print("Reading processed queue:")
                        self.read_processed_queue()
                        break
                    else:
                        print(f"Queue empty, waiting {self.wait_time} seconds")
                        time.sleep(self.wait_time)
        except KeyboardInterrupt:
            print("Stopping queue processing")
        finally:
            self.close()

    def close(self) -> None:
        """Close connections to Redis."""
        if self.redis_client:
            self.redis_client.close()
            print("Redis connection closed") 