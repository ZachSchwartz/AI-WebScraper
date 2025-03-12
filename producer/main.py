"""
Main entry point for the web scraper producer.
"""
import time
import schedule
from src.scraper import Scraper
from src.queue_manager import QueueManager

def run_scraper(queue_manager):
    """Run the scraper and publish results to the queue."""
    try:
        print("Starting scraping job")
        
        # Default scraper config
        scraper_config = {
            'targets': [
                {
                    'url': 'https://example.com',
                    'container_selector': '.item-container',
                    'fields': {
                        'title': {'selector': 'h2.title'},
                        'price': {'selector': '.price'},
                        'description': {'selector': '.description'}
                    }
                }
            ]
        }
        
        scraper = Scraper(scraper_config)
        results = scraper.scrape()
        
        if results:
            print(f"Scraped {len(results)} items")
            
            # Publish results to the queue
            for item in results:
                queue_manager.publish_item(item)
            
            print(f"Published {len(results)} items to queue")
        else:
            print("No results found during scraping")
            
    except Exception as e:
        print(f"Error in scraping job: {str(e)}")

def main():
    """Main entry point for the scraper."""
    print("Starting producer service")
    
    # Simple default queue config
    queue_config = {
        'type': 'redis',
        'host': 'redis',  # Docker service name
        'port': 6379,
        'queue_name': 'scraped_items'
    }
    
    # Initialize queue manager
    queue_manager = QueueManager(queue_config)
    print("Queue manager initialized")
    
    # Run scraper every 60 minutes
    schedule.every(60).minutes.do(run_scraper, queue_manager=queue_manager)
    
    # Run once at startup
    print("Running initial scraping job at startup")
    run_scraper(queue_manager)
    
    # Keep the script running
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()