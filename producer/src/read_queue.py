"""
Utility script to read and display Redis queue contents.
"""

import json
import redis
from typing import List, Dict, Any


def read_queue(queue_name: str = "scraped_items") -> List[Dict[str, Any]]:
    """Read all items from the Redis queue."""
    # Connect to Redis
    redis_client = redis.Redis(
        host="redis",  # Use 'redis' as host when running in Docker
        port=6379,
        decode_responses=True  # This will automatically decode JSON strings
    )
    
    # Get queue length
    queue_length = redis_client.llen(queue_name)
    print(f"\nFound {queue_length} items in queue '{queue_name}'\n")
    
    # Read all items
    items = []
    for i in range(queue_length):
        # Get item but don't remove it from queue
        item_json = redis_client.lindex(queue_name, i)
        if item_json:
            try:
                item = json.loads(item_json)
                items.append(item)
            except json.JSONDecodeError as e:
                print(f"Error decoding item {i}: {e}")
                print(f"Raw content: {item_json}")
    
    return items


def display_items(items: List[Dict[str, Any]]) -> None:
    """Display items in a readable format."""
    for i, item in enumerate(items, 1):
        print(f"\n--- Item {i} ---")
        # Display key information
        print(f"Source URL: {item.get('source_url', 'N/A')}")
        print(f"Link URL: {item.get('href', 'N/A')}")
        print(f"Link Text: {item.get('text', 'N/A')}")
        print(f"Title: {item.get('title', 'N/A')}")
        
        # Display context if available
        if 'context' in item:
            print("\nContext:")
            context = item['context']
            if context.get('previous_text'):
                print(f"Previous text: {context['previous_text']}")
            if context.get('next_text'):
                print(f"Next text: {context['next_text']}")
        
        # Display metadata if available
        if 'metadata' in item:
            print("\nMetadata:")
            for key, value in item['metadata'].items():
                print(f"{key}: {value}")
        
        print("-" * 50)


if __name__ == "__main__":
    items = read_queue()
    if items:
        display_items(items)
    else:
        print("No items found in queue") 