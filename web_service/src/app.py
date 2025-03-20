from flask import Flask, render_template, request, jsonify
import requests
import os
import time
import logging
import socket

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

PRODUCER_SERVICE_URL = os.getenv('PRODUCER_SERVICE_URL', 'http://producer:5000')
LLM_SERVICE_URL = os.getenv('LLM_SERVICE_URL', 'http://llm:5000')
DB_SERVICE_URL = os.getenv('DB_SERVICE_URL', 'http://db_processor:5000')

def check_service_connection(service_url: str) -> bool:
    """Check if a service is reachable."""
    try:
        # Extract hostname from URL
        hostname = service_url.split('://')[1].split(':')[0]
        port = int(service_url.split(':')[-1])
        
        # Try to resolve hostname
        logger.info(f"Resolving hostname: {hostname}")
        ip = socket.gethostbyname(hostname)
        logger.info(f"Resolved to IP: {ip}")
        
        # Try to connect to port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((ip, port))
        sock.close()
        
        if result == 0:
            logger.info(f"Service at {service_url} is reachable")
            return True
        else:
            logger.error(f"Service at {service_url} is not reachable (port {port} is closed)")
            return False
    except Exception as e:
        logger.error(f"Error checking service connection: {str(e)}")
        return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/scrape', methods=['POST'])
def scrape():
    logger.info("Received scrape request")
    data = request.json
    url = data.get('url')
    keyword = data.get('keyword')
    
    if not url or not keyword:
        logger.error("Missing URL or keyword in request")
        return jsonify({'error': 'URL and keyword are required'}), 400
    
    try:
        # Check producer service connection first
        logger.info(f"Checking producer service connection at {PRODUCER_SERVICE_URL}")
        if not check_service_connection(PRODUCER_SERVICE_URL):
            return jsonify({
                'error': 'Producer service is not reachable',
                'status': 'error'
            }), 503

        logger.info(f"Calling producer service for URL: {url}, keyword: {keyword}")
        # Call the producer service
        producer_response = requests.post(
            f"{PRODUCER_SERVICE_URL}/scrape",
            json={'url': url, 'keyword': keyword},
            timeout=30  # Add timeout
        )
        producer_response.raise_for_status()
        producer_data = producer_response.json()
        logger.info(f"Producer service response: {producer_data}")

        # Wait for producer to finish processing by checking Redis queue
        logger.info("Waiting for producer to finish processing...")
        max_retries = 10  # 10 attempts
        retry_delay = 1  # 1 second between attempts
        
        for attempt in range(max_retries):
            try:
                # Check Redis queue length
                redis_response = requests.get(f"{PRODUCER_SERVICE_URL}/queue/status")
                redis_response.raise_for_status()
                queue_status = redis_response.json()
                
                if queue_status.get('items_ready', False):
                    logger.info("Producer has items ready in queue")
                    break
                    
                logger.info(f"Waiting for items in queue, attempt {attempt + 1}/{max_retries}")
                time.sleep(retry_delay)
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Error checking queue status: {str(e)}")
                if attempt == max_retries - 1:
                    raise
                time.sleep(retry_delay)

        # Call the LLM service to get results
        logger.info("Calling LLM service")
        llm_response = requests.post(f"{LLM_SERVICE_URL}/process")
        llm_response.raise_for_status()
        llm_data = llm_response.json()
        logger.info(f"LLM service response: {llm_data}")

        for attempt in range(max_retries):
            try:
                # Check Redis queue length
                redis_response = requests.get(f"{LLM_SERVICE_URL}/queue/status")
                redis_response.raise_for_status()
                queue_status = redis_response.json()
                
                if queue_status.get('items_ready', False):
                    logger.info("Producer has items ready in queue")
                    break
                    
                logger.info(f"Waiting for items in queue, attempt {attempt + 1}/{max_retries}")
                time.sleep(retry_delay)
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Error checking queue status: {str(e)}")
                if attempt == max_retries - 1:
                    raise
                time.sleep(retry_delay)

        #         # Call the LLM service to get results
        logger.info("Calling db service")
        db_response = requests.post(f"{DB_SERVICE_URL}/process")
        db_response.raise_for_status()
        db_data = db_response.json()
        logger.info(f"db service response: {db_data}")

        for attempt in range(max_retries):
            try:
                # Check Redis queue length
                redis_response = requests.get(f"{DB_SERVICE_URL}/queue/status")
                redis_response.raise_for_status()
                queue_status = redis_response.json()
                
                if queue_status.get('items_ready', False):
                    logger.info("Producer has items ready in queue")
                    break
                    
                logger.info(f"Waiting for items in queue, attempt {attempt + 1}/{max_retries}")
                time.sleep(retry_delay)
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Error checking queue status: {str(e)}")
                if attempt == max_retries - 1:
                    raise
                time.sleep(retry_delay)

        return jsonify(llm_data)
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {str(e)}")
        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000) 