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
import time
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
from queue_manager import QueueManager

app = Flask(__name__)

def trigger_llm_processing():
    """Trigger LLM processing of the scraped items."""
    llm_service_url = os.environ.get("LLM_SERVICE_URL", "http://llm:5000")
    max_retries = 5
    retry_delay = 2  # seconds
    
    for attempt in range(max_retries):
        try:
            print(f"Attempting to trigger LLM processing (attempt {attempt + 1}/{max_retries})")
            response = requests.post(f"{llm_service_url}/process")
            response.raise_for_status()
            print("Successfully triggered LLM processing")
            return True
        except requests.exceptions.RequestException as e:
            print(f"Error triggering LLM processing (attempt {attempt + 1}/{max_retries}): {str(e)}")
            if attempt < max_retries - 1:
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print("Max retries exceeded for LLM processing")
                return False

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
            
            # Trigger LLM processing after successful scraping
            trigger_llm_processing()
        else:
            print("No results found during scraping")

    except (requests.exceptions.RequestException, ValueError) as e:
        print(f"Error in scraping job: {str(e)}")
        raise
    except Exception as e:
        print(f"Unexpected error in scraping job: {str(e)}")
        raise

@app.route('/scrape', methods=['POST'])
def scrape_endpoint():
    """API endpoint to handle scraping requests."""
    data = request.json
    url = data.get('url')
    keyword = data.get('keyword')
    
    if not url or not keyword:
        return jsonify({'error': 'URL and keyword are required'}), 400
    
    try:
        # Initialize queue manager
        queue_config = {
            "type": "redis",
            "host": os.environ.get("REDIS_HOST", "redis"),
            "port": 6379,
            "queue_name": "scraped_items",
        }
        queue_manager = QueueManager(queue_config)
        
        # Clear queues before starting
        queue_manager.clear_queues()
        run_scraper(queue_manager, url, keyword)
        
        # Read queue contents
        queue_items = queue_manager.read_queue()
        
        # Close queue manager
        queue_manager.close()
        
        return jsonify({
            'message': 'Scraping completed successfully',
            'status': 'success',
            'details': {
                'url': url,
                'keyword': keyword,
                'timestamp': datetime.now().isoformat(),
                'queue_items': queue_items  # Include queue contents in response
            }
        })
    except Exception as e:
        return jsonify({
            'error': str(e),
            'status': 'error'
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
        # Clear queues before starting
        queue_manager.clear_queues()
        print(f"Scraping URL: {target_url} with keyword: {target_keyword} in main")
        run_scraper(queue_manager, target_url, target_keyword)
    finally:
        queue_manager.read_queue()
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
