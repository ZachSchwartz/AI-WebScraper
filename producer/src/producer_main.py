"""
Main entry point for the web scraper producer.
"""

import argparse
import os
import sys
from typing import Optional
import requests
from flask import Flask, request, jsonify
from scraper import scrape
from datetime import datetime
import logging
import json
import redis

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
from queue_manager import QueueManager

app = Flask(__name__)

def get_redis_client():
    """Get a Redis client connection."""
    try:
        client = redis.Redis(
            host=os.environ.get("REDIS_HOST", "redis"),
            port=6379,
            decode_responses=True
        )
        client.ping()  # Test connection
        return client
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {str(e)}")
        raise

def run_scraper(
    queue_manager: QueueManager, target_url: str, target_keyword: str
) -> None:
    """Run the scraper and publish results to the queue."""
    try:
        print("Starting scraping job")
        scraper_config = {
            "targets": [
                {
                    "url": target_url,
                    "keyword": target_keyword,
                    "container_selector": "body",  # Or a more specific container
                    "fields": {
                        "links": {
                            "selector": "a",  # Target all <a> tags
                            "extract": [
                                "href",
                                "text",
                                "title",
                                "aria-label",
                                "rel",
                            ],  # Extract link attributes
                        },
                        "context": {
                            "selector": "p, h1, h2, h3, li",  # Extract surrounding text
                            "extract": "text",
                        },
                        "metadata": {
                            "selector": "meta",  # Extract meta tags (e.g., description, keywords)
                            "extract": ["name", "content"],
                        },
                    },
                }
            ]
        }

        # Call the standalone scrape function
        results = scrape(scraper_config)
        if results:
            print(f"Scraped {len(results)} items")

            # Publish results to the queue
            for item in results:
                queue_manager.publish_item(item)

            print(f"Published {len(results)} items to queue")
            
            # Get the first item from the queue using rpop (FIFO order)
            redis_client = get_redis_client()
            queue_name = "scraped_items"
            item_json = redis_client.rpop(queue_name)
            
            if item_json:
                first_item = json.loads(item_json)
                # Push the item back to the front of the queue since we want to keep it
                redis_client.lpush(queue_name, item_json)
                return first_item
            else:
                print("No items found in queue after publishing")
                return None

        else:
            print("No results found during scraping")
            return None

    except (requests.exceptions.RequestException, ValueError) as e:
        print(f"Error in scraping job: {str(e)}")
        raise
    except Exception as e:
        print(f"Unexpected error in scraping job: {str(e)}")
        raise

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    try:
        # Check Redis connection
        queue_config = {
            "type": "redis",
            "host": os.environ.get("REDIS_HOST", "redis"),
            "port": 6379,
            "queue_name": "scraped_items",
        }
        queue_manager = QueueManager(queue_config)
        queue_manager.redis_client.ping()
        queue_manager.close()
        
        return jsonify({
            'status': 'healthy',
            'service': 'producer',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'service': 'producer',
            'error': str(e)
        }), 500

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
        queue_length = queue_manager.redis_client.llen("scraped_items")
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

@app.route('/scrape', methods=['POST'])
def scrape_endpoint():
    """API endpoint to handle scraping requests."""
    logger.info("Received scrape request")
    data = request.json
    logger.info(f"Request data: {data}")
    
    url = data.get('url')
    keyword = data.get('keyword')
    
    if not url or not keyword:
        logger.error("Missing URL or keyword in request")
        return jsonify({'error': 'URL and keyword are required'}), 400
    
    try:
        logger.info("Initializing queue manager")
        queue_config = {
            "type": "redis",
            "host": os.environ.get("REDIS_HOST", "redis"),
            "port": 6379,
            "queue_name": "scraped_items",
        }
        logger.info(f"Queue config: {queue_config}")
        queue_manager = QueueManager(queue_config)
        queue_manager.clear_queues()
        
        logger.info("Starting scraper")
        first_item = run_scraper(queue_manager, url, keyword)
        
        if first_item:
            # Return just the scraped data without any wrapper
            return jsonify(first_item)
        else:
            return jsonify({
                'error': 'No items found after scraping'
            }), 404
        
    except Exception as e:
        logger.error(f"Error in scraping endpoint: {str(e)}", exc_info=True)
        return jsonify({
            'error': str(e)
        }), 500

def main(target_url: str, target_keyword: str) -> None:
    """Main entry point for the scraper when run directly."""
    queue_config = {
        "type": "redis",
        "host": os.environ.get("REDIS_HOST", "redis"),
        "port": 6379,
        "queue_name": "scraped_items",
    }

    queue_manager = QueueManager(queue_config)
    print("Queue manager initialized")

    try:
        print(f"Scraping URL: {target_url} with keyword: {target_keyword} in main")
        first_item = run_scraper(queue_manager, target_url, target_keyword)
        if first_item:
            print("First item from queue:")
            print(json.dumps(first_item, indent=2))
    finally:
        queue_manager.close()

if __name__ == "__main__":
    # Check if we're running in API mode (no arguments)
    if len(sys.argv) == 1:
        # Run as API server
        app.run(host='0.0.0.0', port=5000)
    else:
        # Run as command line tool
        # Try to get URL and keyword from environment variables first
        url: Optional[str] = os.environ.get("URL")
        keyword: Optional[str] = os.environ.get("KEYWORD")

        # If not in environment, try command line arguments
        if not url or not keyword:
            parser = argparse.ArgumentParser(description="Web scraper producer")
            parser.add_argument("--url", required=True, help="Target URL to scrape")
            parser.add_argument("--keyword", required=True, help="Keyword to search for")
            args = parser.parse_args()
            url = args.url
            keyword = args.keyword

        if not url or not keyword:
            print("Error: URL and keyword are required")
            sys.exit(1)

        print(f"Scraping URL: {url} with keyword: {keyword}")
        main(url, keyword)
