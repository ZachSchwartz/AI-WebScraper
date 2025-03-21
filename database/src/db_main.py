"""
Main entry point for the database processor.
Takes processed items from Redis queue and stores them in SQL database.
"""

import os
import sys
from flask import Flask, request, jsonify
from db_processor import DatabaseProcessor
from datetime import datetime

# Add root directory to path for importing queue_manager
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
from queue_manager import QueueManager

app = Flask(__name__)

@app.route('/queue/status', methods=['GET'])
def queue_status():
    """Check if items are ready in the Redis queue."""
    try:
        queue_config = {
            "type": "redis",
            "host": os.environ.get("REDIS_HOST", "redis"),
            "port": 6379,
            "queue_name": "scraped_items",
        }
        queue_manager = QueueManager(queue_config)
        
        # Check queue length
        queue_length = queue_manager.redis_client.llen(queue_manager.processed_queue_name)
        queue_manager.close()
        
        return jsonify({
            'items_ready': queue_length == 0,
            'queue_length': queue_length,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error checking queue status: {str(e)}")
        return jsonify({
            'error': str(e),
            'items_ready': False
        }), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    try:
        # Check Redis connection
        redis_config = {
            "type": "redis",
            "host": os.environ.get("REDIS_HOST", "localhost"),
            "port": 6379,
            "queue_name": "scraped_items",
        }
        queue_manager = QueueManager(redis_config)
        queue_manager.redis_client.ping()
        queue_manager.close()
        
        # Check database connection
        db_processor = DatabaseProcessor()
        db_processor.engine.connect()
        
        return jsonify({
            'status': 'healthy',
            'service': 'db_processor',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'service': 'db_processor',
            'error': str(e)
        }), 500

def process_queue():
    """Process items from the queue."""
    print("Starting database processor...")
    
    # Configure Redis connection
    redis_config = {
        "type": "redis",
        "host": os.environ.get("REDIS_HOST", "redis"),
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
    queue_manager.process_queue(lambda item: db_processor.process_item(item))
    
    print("Database processing complete.")

@app.route('/process', methods=['POST'])
def process_endpoint():
    """API endpoint to trigger queue processing."""
    try:
        # Configure Redis connection
        redis_config = {
            "type": "redis",
            "host": os.environ.get("REDIS_HOST", "redis"),
            "port": 6379,
            "queue_name": "scraped_items_processed",
        }

        # Initialize Redis connection
        queue_manager = QueueManager(redis_config)
        
        # Initialize database processor
        db_processor = DatabaseProcessor()
        # Process items from the queue
        items = queue_manager.process_queue(lambda item: db_processor.process_item(item))
        # items = queue_manager.read_queue(queue_manager.processed_queue_name)

        queue_manager.clear_queues()
        
        return jsonify({
            'message': items
        })
    except Exception as e:
        return jsonify({
            'error': str(e),
            'status': 'error',
            'details': {
                'db_status': 'Error storing data in database'
            }
        }), 500

def main() -> None:
    """Initialize and run the database processor."""
    # Check if we're running in API mode (no arguments)
    if len(sys.argv) == 1:
        # Run as API server
        app.run(host='0.0.0.0', port=5000)
    else:
        # Run as command line tool
        process_queue()

if __name__ == "__main__":
    main() 