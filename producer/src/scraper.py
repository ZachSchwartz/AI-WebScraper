"""
Web scraper module for collecting data from target websites.
"""
import time
import random
from typing import Dict, List, Any, Optional
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

class Scraper:
    """Web scraper class to extract data from websites."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the scraper with configuration.
        
        Args:
            config: Dictionary containing scraper configuration
        """
        self.targets = config.get('targets', [])
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        self.timeout = 30
        self.retry_count = 3
        self.driver = None
        
    def _init_selenium(self) -> None:
        """Initialize Selenium WebDriver for JavaScript rendering."""
        if self.driver:
            return
            
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument(f"user-agent={self.headers['User-Agent']}")
            
        try:
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.driver.set_page_load_timeout(self.timeout)
        except Exception as e:
            print(f"Failed to initialize Selenium: {str(e)}")
            self.driver = None
            
    def _close_selenium(self) -> None:
        """Close Selenium WebDriver."""
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                print(f"Error closing Selenium driver: {str(e)}")
            finally:
                self.driver = None
                
    def _fetch_with_requests(self, url: str) -> Optional[str]:
        """
        Fetch URL content using requests library.
        
        Args:
            url: Target URL
            
        Returns:
            HTML content as string or None if failed
        """            
        for attempt in range(self.retry_count):
            try:
                response = requests.get(
                    url, 
                    headers=self.headers,
                    timeout=self.timeout
                )
                response.raise_for_status()
                return response.text
            except requests.exceptions.RequestException as e:
                print(f"Attempt {attempt+1}/{self.retry_count} failed for {url}: {str(e)}")
                if attempt < self.retry_count - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                    
        print(f"Failed to fetch {url} after {self.retry_count} attempts")
        return None
        
    def _parse_content(self, html: str, target_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Parse HTML content based on target configuration.
        
        Args:
            html: HTML content as string
            target_config: Configuration for parsing this target
            
        Returns:
            List of parsed items
        """
        results = []
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Find container elements
            container_selector = target_config.get('container_selector')
            containers = soup.select(container_selector) if container_selector else [soup]
            
            for container in containers:
                item = {}
                
                # Parse fields based on config
                for field_name, field_config in target_config.get('fields', {}).items():
                    selector = field_config.get('selector')
                    attribute = field_config.get('attribute')
                    
                    elements = container.select(selector) if selector else []
                    if elements:
                        element = elements[0]
                        if attribute and attribute != 'text':
                            item[field_name] = element.get(attribute, '')
                        else:
                            item[field_name] = element.get_text(strip=True)
                    else:
                        item[field_name] = field_config.get('default', '')
                
                # Add timestamp and source URL
                item['scraped_at'] = int(time.time())
                item['source_url'] = target_config.get('url', '')
                
                results.append(item)
                    
            return results
                
        except Exception as e:
            print(f"Error parsing content: {str(e)}")
            return []
            
    def _scrape_target(self, target_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Scrape a single target based on configuration.
        
        Args:
            target_config: Configuration for this target
            
        Returns:
            List of scraped items
        """
        url = target_config.get('url')
        if not url:
            print("Target missing URL")
            return []
            
        print(f"Scraping target: {url}")
        
        # Apply rate limiting
        time.sleep(random.uniform(2, 5))
        
        # Fetch content
        html = self._fetch_with_requests(url)
            
        if not html:
            print(f"No content retrieved from {url}")
            return []
            
        # Parse content
        return self._parse_content(html, target_config)
        
    def scrape(self) -> List[Dict[str, Any]]:
        """
        Scrape all configured targets.
        
        Returns:
            List of all scraped items
        """
        all_results = []
        
        try:
            for target_config in self.targets:
                results = self._scrape_target(target_config)
                if results:
                    print(f"Scraped {len(results)} items from {target_config.get('url')}")
                    all_results.extend(results)
                else:
                    print(f"No results from {target_config.get('url')}")
                    
        finally:
            self._close_selenium()
            
        return all_results