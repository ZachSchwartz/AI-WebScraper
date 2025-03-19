from flask import Flask, render_template, request, jsonify
import requests
import os

app = Flask(__name__)

PRODUCER_SERVICE_URL = os.getenv('PRODUCER_SERVICE_URL', 'http://producer:5000')

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
        response = requests.post(
            f"{PRODUCER_SERVICE_URL}/scrape",
            json={'url': url, 'keyword': keyword}
        )
        response.raise_for_status()
        return jsonify(response.json())
    except requests.exceptions.RequestException as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000) 