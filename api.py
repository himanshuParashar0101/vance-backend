from flask import Flask, request, jsonify
from flask_cors import CORS
from flasgger import Swagger
import sqlite3
from datetime import datetime, timedelta
import scraper
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)
CORS(app)
swagger = Swagger(app)

DATABASE_PATH = os.getenv('DATABASE_PATH', 'yahoo_finance.db')

def check_or_create_table(table_name):
    abs_path = os.path.abspath(DATABASE_PATH)
    print(f"Looking for database at {abs_path}")
    if not os.path.exists(abs_path):
        print(f"Database file not found at {abs_path}.")
        raise sqlite3.OperationalError("Database file not found.")
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
    if cursor.fetchone() is None:
        scraper.create_table(table_name)
    conn.close()

def get_existing_date_range(table_name, start_date, end_date):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    query = f'''
        SELECT MIN(date), MAX(date) FROM {table_name} WHERE date BETWEEN ? AND ?
    '''
    cursor.execute(query, (start_date, end_date))
    result = cursor.fetchone()
    conn.close()
    return result

def query_data(table_name, start_date, end_date):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    query = f'''
        SELECT date, open, high, low, close, adj_close, volume 
        FROM {table_name}
        WHERE date BETWEEN ? AND ?
    '''
    cursor.execute(query, (start_date, end_date))
    rows = cursor.fetchall()
    conn.close()
    return rows

@app.route('/api/forex_data', methods=['POST'])
def get_forex_data():
    """
    Get historical forex data.
    ---
    parameters:
      - name: from
        in: query
        type: string
        required: true
        description: The currency to convert from (e.g., USD).
      - name: to
        in: query
        type: string
        required: true
        description: The currency to convert to (e.g., INR).
      - name: period
        in: query
        type: string
        required: true
        description: The time period to retrieve data for (e.g., 1W, 1M, 3M, 6M, 1Y).
    responses:
      200:
        description: A list of forex data points
        schema:
          type: array
          items:
            type: object
            properties:
              date:
                type: string
                description: The date of the data point.
              open:
                type: number
                description: The opening value.
              high:
                type: number
                description: The highest value.
              low:
                type: number
                description: The lowest value.
              close:
                type: number
                description: The closing value.
              adj_close:
                type: number
                description: The adjusted closing value.
              volume:
                type: integer
                description: The trading volume.
      400:
        description: Missing required parameters or invalid period.
      404:
        description: No data found for the given parameters.
      500:
        description: Failed to retrieve data.
    """
    print("****************REQUEST RECEIVED****************")
    from_currency = request.args.get('from')
    to_currency = request.args.get('to')
    period = request.args.get('period')

    if not from_currency or not to_currency or not period:
        return jsonify({"error": "Missing required parameters"}), 400

    table_name = f"{from_currency}{to_currency}"
    period_map = {'1W': 7, '1M': 30, '3M': 90, '6M': 180, '1Y': 365}
    
    if period not in period_map:
        return jsonify({"error": "Invalid period"}), 400

    end_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = end_date - timedelta(days=period_map[period])
    start_date_str = start_date.strftime('%Y-%m-%d')
    end_date_str = end_date.strftime('%Y-%m-%d')

    print(f"Required data for Conversion {from_currency} to {to_currency} for Period: {period}")

    check_or_create_table(table_name)

    existing_start, existing_end = get_existing_date_range(table_name, start_date_str, end_date_str)

    if existing_start is None:
        print("Data not present in database. Scraping full range.")
        from_timestamp = int(start_date.timestamp())
        to_timestamp = int(end_date.timestamp())
        scraped_data = scraper.scrape_data(table_name + "=X", from_timestamp, to_timestamp, from_currency, to_currency)
        
        if scraped_data:
            scraper.insert_data(table_name, scraped_data)
            results = query_data(table_name, start_date_str, end_date_str)
        else:
            return jsonify({"error": "Failed to retrieve data"}), 500
    else:
        existing_start_date = datetime.strptime(existing_start, '%Y-%m-%d')
        existing_end_date = datetime.strptime(existing_end, '%Y-%m-%d')

        if start_date < existing_start_date:
            missing_start_date = start_date
            missing_end_date = existing_start_date - timedelta(days=1)

            print(f"Scraping missing data from {missing_start_date} to {missing_end_date}.")
            from_timestamp = int(missing_start_date.timestamp())
            to_timestamp = int(missing_end_date.timestamp())
            scraped_data = scraper.scrape_data(table_name + "=X", from_timestamp, to_timestamp, from_currency, to_currency)
            
            if scraped_data:
                scraper.insert_data(table_name, scraped_data)

        if existing_end_date < end_date:
            missing_start_date = existing_end_date + timedelta(days=1)
            missing_end_date = end_date

            print(f"Scraping missing data from {missing_start_date} to {missing_end_date}.")
            quote = table_name + "=X"
            from_timestamp = int(missing_start_date.timestamp())
            to_timestamp = int(missing_end_date.timestamp())
            scraped_data = scraper.scrape_data(quote, from_timestamp, to_timestamp, from_currency, to_currency)
            
            if scraped_data:
                scraper.insert_data(table_name, scraped_data)
        
        results = query_data(table_name, start_date_str, end_date_str)

    response = [
        {
            'date': row[0],
            'open': row[1],
            'high': row[2],
            'low': row[3],
            'close': row[4],
            'adj_close': row[5],
            'volume': row[6]
        } for row in results
    ]

    if not response:
        return jsonify({"error": "No data found for the given parameters"}), 404

    print("==================SUCCESS SENDING RESPONSE==================")
    return jsonify(response)

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
