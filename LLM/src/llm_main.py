"""
Main entry point for the LLM processor.
"""

import os
import sys
import json
import requests
from flask import Flask, request, jsonify
from llm_processor import LLMProcessor
from datetime import datetime
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
from queue_manager import QueueManager

app = Flask(__name__)

def trigger_db_processing():
    """Trigger database processing of the LLM-processed items."""
    db_service_url = os.environ.get("DB_SERVICE_URL", "http://db_processor:5000")
    try:
        response = requests.post(f"{db_service_url}/process")
        response.raise_for_status()
        print("Successfully triggered database processing")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error triggering database processing: {str(e)}")
        return False

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
    queue_manager.process_queue(processor.process_item)

    # Print queue length after processing
    print("\nAfter processing:")
    input_queue_length = queue_manager.redis_client.llen(queue_manager.queue_name)
    processed_queue_length = queue_manager.redis_client.llen(queue_manager.processed_queue_name)
    print(f"Input queue '{queue_manager.queue_name}' length: {input_queue_length}")
    print(f"Processed queue '{queue_manager.processed_queue_name}' length: {processed_queue_length}")
    
    # Trigger database processing after successful LLM processing
    trigger_db_processing()

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
        
        # Get queue length before processing
        input_queue_length = queue_manager.redis_client.llen(queue_manager.queue_name)
        
        # Process items
        processor = LLMProcessor()
        processed_items = queue_manager.process_queue(processor.process_item)
        
        # Get queue length after processing
        processed_queue_length = queue_manager.redis_client.llen(queue_manager.processed_queue_name)
        
        return jsonify({
            'message': 'LLM processing completed successfully',
            'status': 'success',
            'details': {
                'items_processed': len(processed_items),
                'input_queue_length': input_queue_length,
                'processed_queue_length': processed_queue_length,
                'timestamp': datetime.now().isoformat(),
                'results': processed_items
            }
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
