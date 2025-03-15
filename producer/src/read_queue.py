"""
Utility script to read and display Redis queue contents.
"""

import json
import redis
from typing import List, Dict, Any
from loguru import logger


def format_dict(d: Dict[str, Any], indent: int = 0) -> None:
    """Format and print a dictionary with proper indentation."""
    for key, value in d.items():
        indent_str = "  " * indent
        if isinstance(value, dict):
            logger.info(f"{indent_str}{key}:")
            format_dict(value, indent + 1)
        elif isinstance(value, list):
            logger.info(f"{indent_str}{key}:")
            for item in value:
                if isinstance(item, dict):
                    format_dict(item, indent + 1)
                else:
                    logger.info(f"{indent_str}  - {item}")
        else:
            logger.info(f"{indent_str}{key}: {value}")


def read_queue(redis_client=None, queue_name: str = "scraped_items", max_items: int = 5) -> List[Dict[str, Any]]:
    """
    Read and display items from a Redis queue.
    
    Args:
        redis_client: Redis client instance. If None, a new connection will be created.
        queue_name: Name of the queue to read from
        max_items: Maximum number of items to display (default: 5)
    
    Returns:
        List of items read from the queue
    """
    try:
        # Create Redis client if not provided
        if redis_client is None:
            redis_client = redis.Redis(
                host="redis",
                port=6379,
                decode_responses=True
            )
        
        # Get queue length
        queue_length = redis_client.llen(queue_name)
        logger.info(f"\nFound {queue_length} items in queue '{queue_name}'")
        logger.info("=" * 80)
        
        # Only display up to max_items
        display_count = min(max_items, queue_length)
        items = []
        
        # Read and display items
        for i in range(display_count):
            item_json = redis_client.lindex(queue_name, i)
            if item_json:
                try:
                    item = json.loads(item_json)
                    items.append(item)
                    
                    logger.info(f"\nItem {i + 1}/{display_count}:")
                    logger.info("=" * 80)
                    format_dict(item)
                    logger.info("=" * 80)
                except json.JSONDecodeError as e:
                    logger.error(f"Error decoding item {i}: {e}")
                    logger.info(f"Raw content: {item_json}")
        
        if queue_length > max_items:
            logger.info(f"\nNote: Displayed first {display_count} items out of {queue_length} total items")
        
        return items
            
    except Exception as e:
        logger.error(f"Error reading queue: {e}")
        return []


if __name__ == "__main__":
    # When run directly, read both queues
    logger.info("Reading unprocessed items queue:")
    read_queue(queue_name="scraped_items")
    
    logger.info("\nReading processed items queue:")
    read_queue(queue_name="scraped_items_processed") 