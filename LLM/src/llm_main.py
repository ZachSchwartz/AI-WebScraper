"""
Main entry point for the LLM processor.
"""

import os
import sys
import logging
import json
import requests
from flask import Flask, request, jsonify
from llm_processor import LLMProcessor
from datetime import datetime
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
            'items_ready': queue_length > 0,
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
        
        return jsonify({
            'status': 'healthy',
            'service': 'llm',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'service': 'llm',
            'error': str(e)
        }), 500

def process_queue():
    """Process items in the queue."""
    # Configure Redis connection
    redis_config = {
        "type": "redis",
        "host": os.environ.get("REDIS_HOST", "localhost"),
        "port": 6379,
        "queue_name": "scraped_items",
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
    # Use lambda to maintain instance context
    queue_manager.process_queue(lambda item: processor.process_item(item))

    # Print queue length after processing
    print("\nAfter processing:")
    input_queue_length = queue_manager.redis_client.llen(queue_manager.queue_name)
    processed_queue_length = queue_manager.redis_client.llen(queue_manager.processed_queue_name)
    print(f"Input queue '{queue_manager.queue_name}' length: {input_queue_length}")
    print(f"Processed queue '{queue_manager.processed_queue_name}' length: {processed_queue_length}")

@app.route('/process', methods=['POST'])
def process_endpoint():
    """API endpoint to trigger queue processing."""
    try:
        # Configure Redis connection
        redis_config = {
            "type": "redis",
            "host": os.environ.get("REDIS_HOST", "localhost"),
            "port": 6379,
            "queue_name": "scraped_items",
            "wait_time": 10,
        }

        # Initialize Redis connection
        queue_manager = QueueManager(redis_config)
        
        # Process items
        processor = LLMProcessor()
        processed_items = queue_manager.process_queue(lambda item: processor.process_item(item))
        
        return jsonify({
            'message': processed_items
        })
    except Exception as e:
        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500

def main() -> None:
    """Initialize and run the LLM processor."""
    # Check if we're running in API mode (no arguments)
    if len(sys.argv) == 1:
        # Run as API server
        app.run(host='0.0.0.0', port=5000)
    else:
        # Run as command line tool
        process_queue()

if __name__ == "__main__":
    main()
