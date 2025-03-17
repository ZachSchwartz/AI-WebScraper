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
                        self.read_queue()
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

    def _format_dict(self, d: Dict[str, Any], indent: int = 0) -> None:
        """Format and print a dictionary with proper indentation."""
        for key, value in d.items():
            indent_str = "  " * indent
            if key == "relevance_analysis" and isinstance(value, dict):
                # Highlight relevance analysis section
                print(f"{indent_str}{key}:")
                print(f"{indent_str}  {'='*40}")
                for k, v in value.items():
                    if k == "score":
                        # Highlight the score with special formatting
                        print(f"{indent_str}  {k}: {'*'*20} {v} {'*'*20}")
                    else:
                        print(f"{indent_str}  {k}: {v}")
                print(f"{indent_str}  {'='*40}")
            elif isinstance(value, dict):
                print(f"{indent_str}{key}:")
                self._format_dict(value, indent + 1)
            elif isinstance(value, list):
                print(f"{indent_str}{key}:")
                for item in value:
                    if isinstance(item, dict):
                        self._format_dict(item, indent + 1)
                    else:
                        print(f"{indent_str}  - {item}")
            else:
                print(f"{indent_str}{key}: {value}")

    def read_queue(self, queue_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Read and display items from a Redis queue.
        
        Args:
            queue_name: Name of the queue to read from. If None, uses self.queue_name
        
        Returns:
            List of items read from the queue
        """
        try:
            queue_name = queue_name or self.queue_name
            
            # Get queue length
            queue_length = self.redis_client.llen(queue_name)
            print(f"\nFound {queue_length} items in queue '{queue_name}'")
            print("=" * 80)
            
            display_count = queue_length
            items = []
            scores = []  # Track scores for summary
            
            # Read and display items
            for i in range(display_count):
                item_json = self.redis_client.lindex(queue_name, i)
                if item_json:
                    try:
                        item = json.loads(item_json)
                        items.append(item)
                        
                        # Extract score if available
                        if "relevance_analysis" in item and "score" in item["relevance_analysis"]:
                            scores.append(item["relevance_analysis"]["score"])
                        
                        print(f"\nItem {i + 1}/{display_count}:")
                        print("=" * 80)
                        self._format_dict(item)
                        print("=" * 80)
                    except json.JSONDecodeError as e:
                        print(f"Error decoding item {i}: {e}")
                        print(f"Raw content: {item_json}")
            
            # Display score summary if we have scores
            if scores:
                print("\nScore Summary:")
                print("=" * 40)
                for i, score in enumerate(scores, 1):
                    print(f"Item {i}: {score}")
                avg_score = sum(scores) / len(scores)
                print(f"Average Score: {avg_score:.3f}")
                print("=" * 40)
            
            return items
                
        except Exception as e:
            print(f"Error reading queue: {e}")
            return []

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
            print(f"Error clearing queues: {str(e)}")
            return False 