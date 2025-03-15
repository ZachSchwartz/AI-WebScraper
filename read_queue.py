"""
Utility script to read and display Redis queue contents.
"""

import json
import redis
from typing import List, Dict, Any
from queue_manager import QueueManager


def format_dict(d: Dict[str, Any], indent: int = 0) -> None:
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


def read_queue(redis_client=None, queue_name: str = "scraped_items") -> List[Dict[str, Any]]:
    """
    Read and display items from a Redis queue.
    
    Args:
        redis_client: Redis client instance. If None, a new connection will be created.
        queue_name: Name of the queue to read from
    
    Returns:
        List of items read from the queue
    """
    try:
        # Create Redis client if not provided
        if redis_client is None:
            queue_config = {
                "type": "redis",
                "host": "redis",
                "port": 6379,
                "queue_name": queue_name
            }
            queue_manager = QueueManager(queue_config)
            redis_client = queue_manager.redis_client
        
        # Get queue length
        queue_length = redis_client.llen(queue_name)
        print(f"\nFound {queue_length} items in queue '{queue_name}'")
        print("=" * 80)
        
        display_count = queue_length
        items = []
        scores = []  # Track scores for summary
        
        # Read and display items
        for i in range(display_count):
            item_json = redis_client.lindex(queue_name, i)
            if item_json:
                try:
                    item = json.loads(item_json)
                    items.append(item)
                    
                    # Extract score if available
                    if "relevance_analysis" in item and "score" in item["relevance_analysis"]:
                        scores.append(item["relevance_analysis"]["score"])
                    
                    print(f"\nItem {i + 1}/{display_count}:")
                    print("=" * 80)
                    format_dict(item)
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
    finally:
        if redis_client and not isinstance(redis_client, redis.Redis):
            redis_client.close()


if __name__ == "__main__":
    # When run directly, read both queues
    print("Reading unprocessed items queue:")
    read_queue(queue_name="scraped_items")
    
    print("\nReading processed items queue:")
    read_queue(queue_name="scraped_items_processed") 