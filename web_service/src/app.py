from flask import Flask, render_template, request, jsonify
import requests
import os
import time

app = Flask(__name__)

PRODUCER_SERVICE_URL = os.getenv('PRODUCER_SERVICE_URL', 'http://producer:5000')
LLM_SERVICE_URL = os.getenv('LLM_SERVICE_URL', 'http://llm:5000')
DB_SERVICE_URL = os.getenv('DB_SERVICE_URL', 'http://db_processor:5000')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/scrape', methods=['POST'])
def scrape():
    data = request.json
    url = data.get('url')
    keyword = data.get('keyword')
    
    if not url or not keyword:
        return jsonify({'error': 'URL and keyword are required'}), 400
    
    try:
        # Call the producer service
        producer_response = requests.post(
            f"{PRODUCER_SERVICE_URL}/scrape",
            json={'url': url, 'keyword': keyword}
        )
        producer_response.raise_for_status()
        producer_data = producer_response.json()

        # Wait a moment for the LLM service to process
        time.sleep(2)

        # Call the LLM service to get results
        llm_response = requests.post(f"{LLM_SERVICE_URL}/process")
        llm_response.raise_for_status()
        llm_data = llm_response.json()

        # Wait a moment for the database service to process
        time.sleep(1)

        # Call the database service to get processing status
        db_response = requests.post(f"{DB_SERVICE_URL}/process")
        db_response.raise_for_status()
        db_data = db_response.json()

        # Combine the results
        combined_data = {
            'message': f"{producer_data['message']}, {llm_data['message']}, and {db_data['message']}",
            'status': 'success' if all(data['status'] == 'success' for data in [producer_data, llm_data, db_data]) else 'error',
            'details': {
                **producer_data['details'],
                **llm_data['details'],
                **db_data['details']
            }
        }

        return jsonify(combined_data)
    except requests.exceptions.RequestException as e:
        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000) 