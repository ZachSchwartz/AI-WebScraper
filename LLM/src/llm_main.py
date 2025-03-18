"""
Main entry point for the LLM processor.
"""

import os
import sys
from llm_processor import LLMProcessor
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
from queue_manager import QueueManager


def main() -> None:
    """Initialize and run the LLM processor."""
    # Configure Redis connection
    redis_config = {
        "type": "redis",
        "host": os.environ.get("REDIS_HOST", "localhost"),  # Use environment variable with localhost as fallback
        "port": 6379,  # Use default Redis port
        "queue_name": "scraped_items",
        # Add wait_time to ensure we don't exit too quickly if the queue is empty
        "wait_time": 10,
    }

    # Initialize Redis connection
    queue_manager = QueueManager(redis_config)
    
    # Print queue length before processing
    print("\nBefore processing:")
    input_queue_length = queue_manager.redis_client.llen(queue_manager.queue_name)
    processed_queue_length = queue_manager.redis_client.llen(queue_manager.processed_queue_name)
    print(f"Input queue '{queue_manager.queue_name}' length: {input_queue_length}")
    print(f"Processed queue '{queue_manager.processed_queue_name}' length: {processed_queue_length}")

    processor = LLMProcessor()
    queue_manager.process_queue(processor.process_item)

    # Print queue length after processing
    print("\nAfter processing:")
    input_queue_length = queue_manager.redis_client.llen(queue_manager.queue_name)
    processed_queue_length = queue_manager.redis_client.llen(queue_manager.processed_queue_name)
    print(f"Input queue '{queue_manager.queue_name}' length: {input_queue_length}")
    print(f"Processed queue '{queue_manager.processed_queue_name}' length: {processed_queue_length}")

    # Display processed items
    print("\nDisplaying processed items:")
    processed_items = queue_manager.read_queue(queue_manager.processed_queue_name)
    
    if not processed_items:
        print("No processed items found in the queue. Trying a direct check...")
        # Try a direct check of the queue
        try:
            for i in range(queue_manager.redis_client.llen(queue_manager.processed_queue_name)):
                item_json = queue_manager.redis_client.lindex(queue_manager.processed_queue_name, i)
                if item_json:
                    print(f"Found raw item in processed queue: {item_json[:100]}...")
        except Exception as e:
            print(f"Error directly checking processed queue: {e}")


if __name__ == "__main__":
    main()
