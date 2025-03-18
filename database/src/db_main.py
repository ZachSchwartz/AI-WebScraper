"""
Main entry point for the database processor.
Takes processed items from Redis queue and stores them in SQL database.
"""

import os
import sys
from db_processor import DatabaseProcessor

# Add root directory to path for importing queue_manager
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
from queue_manager import QueueManager


def main() -> None:
    """Initialize and run the database processor."""
    print("Starting database processor...")
    
    # Configure Redis connection
    redis_config = {
        "type": "redis",
        "host": os.environ.get("REDIS_HOST", "redis"),  # Use environment variable with redis service name as fallback
        "port": 6379,
        "queue_name": "scraped_items",
        "wait_time": 30,
    }

    # Initialize Redis connection
    queue_manager = QueueManager(redis_config)
    
    # Initialize database processor
    db_processor = DatabaseProcessor()
    
    # Process items from the queue
    print(f"Processing items from Redis queue: {redis_config['queue_name']}")
    queue_manager.process_queue(db_processor.process_item)
    
    print("Database processing complete.")


if __name__ == "__main__":
    main() 