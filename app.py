from flask import Flask, render_template, request, jsonify, send_file, Response
import pandas as pd
import requests
import sqlite3
import io
import os
import time
import json

app = Flask(__name__)


@app.template_filter('timestamp_to_date')
def timestamp_to_date(timestamp):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))


DB_FILE = "ip_cache.db"


# Initialize database
def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute('''
                 CREATE TABLE IF NOT EXISTS ip_cache
                 (
                     ip
                     TEXT
                     PRIMARY
                     KEY,
                     country
                     TEXT,
                     region
                     TEXT,
                     city
                     TEXT
                 )
                 ''')
    conn.commit()
    conn.close()


init_db()


def get_ip_location(ip, use_delay=False):
    # Check cache first
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.execute('SELECT country, region, city FROM ip_cache WHERE ip = ?', (ip,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return {"country": row[0], "region": row[1], "city": row[2]}

    if use_delay:
        time.sleep(0.5)  # Rate limiting

    # Retry logic with exponential backoff
    for attempt in range(3):
        try:
            response = requests.get(f"http://ip-api.com/json/{ip}", timeout=15)
            
            if response.status_code == 429:  # Rate limited
                time.sleep(2 ** attempt)  # Exponential backoff
                continue
                
            data = response.json()

            if data.get("status") == "success":
                result = {
                    "country": data.get("country") or "Unknown",
                    "region": data.get("regionName") or "Unknown",
                    "city": data.get("city") or "Unknown"
                }
                break
            else:
                result = {"country": "Unknown", "region": "Unknown", "city": "Unknown"}
                break
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.RequestException):
            if attempt < 2:
                time.sleep(2 ** attempt)  # Exponential backoff
                continue
            result = {"country": "Network Error", "region": "Network Error", "city": "Network Error"}
        except Exception:
            result = {"country": "Error", "region": "Error", "city": "Error"}
            break

    # Save to cache
    conn = sqlite3.connect(DB_FILE)
    conn.execute('INSERT OR REPLACE INTO ip_cache (ip, country, region, city) VALUES (?, ?, ?, ?)',
                 (ip, result["country"], result["region"], result["city"]))
    conn.commit()
    conn.close()

    return result


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/stats')
def view_stats():
    conn = sqlite3.connect(DB_FILE)

    # Get total records
    total_cursor = conn.execute('SELECT COUNT(*) FROM ip_cache')
    total_ips = total_cursor.fetchone()[0]

    # Top countries
    country_cursor = conn.execute(
        'SELECT country, COUNT(*) as count FROM ip_cache WHERE country != "Unknown" GROUP BY country ORDER BY count DESC LIMIT 10')
    top_countries = country_cursor.fetchall()

    # Top regions
    region_cursor = conn.execute(
        'SELECT region, country, COUNT(*) as count FROM ip_cache WHERE region != "Unknown" GROUP BY region, country ORDER BY count DESC LIMIT 10')
    top_regions = region_cursor.fetchall()

    # Top cities
    city_cursor = conn.execute(
        'SELECT city, region, country, COUNT(*) as count FROM ip_cache WHERE city != "Unknown" GROUP BY city, region, country ORDER BY count DESC LIMIT 10')
    top_cities = city_cursor.fetchall()

    # Unknown/Error counts
    unknown_cursor = conn.execute(
        'SELECT COUNT(*) FROM ip_cache WHERE country = "Unknown" OR region = "Unknown" OR city = "Unknown"')
    unknown_count = unknown_cursor.fetchone()[0]

    error_cursor = conn.execute(
        'SELECT COUNT(*) FROM ip_cache WHERE country = "Error" OR region = "Error" OR city = "Error"')
    error_count = error_cursor.fetchone()[0]

    conn.close()

    return render_template('stats.html',
                           total_ips=total_ips,
                           top_countries=top_countries,
                           top_regions=top_regions,
                           top_cities=top_cities,
                           unknown_count=unknown_count,
                           error_count=error_count)


@app.route('/cache')
def view_cache():
    page = int(request.args.get('page', 1))
    per_page = 50
    search = request.args.get('search', '').strip()

    conn = sqlite3.connect(DB_FILE)

    # Build query with search filter
    if search:
        query = 'SELECT ip, country, region, city FROM ip_cache WHERE ip LIKE ? OR country LIKE ? OR region LIKE ? OR city LIKE ? ORDER BY ip LIMIT ? OFFSET ?'
        search_term = f'%{search}%'
        cursor = conn.execute(query,
                              (search_term, search_term, search_term, search_term, per_page, (page - 1) * per_page))

        # Get total count for pagination
        count_cursor = conn.execute(
            'SELECT COUNT(*) FROM ip_cache WHERE ip LIKE ? OR country LIKE ? OR region LIKE ? OR city LIKE ?',
            (search_term, search_term, search_term, search_term))
        total = count_cursor.fetchone()[0]
    else:
        cursor = conn.execute('SELECT ip, country, region, city FROM ip_cache ORDER BY ip LIMIT ? OFFSET ?',
                              (per_page, (page - 1) * per_page))
        count_cursor = conn.execute('SELECT COUNT(*) FROM ip_cache')
        total = count_cursor.fetchone()[0]

    cache_data = cursor.fetchall()
    conn.close()

    total_pages = (total + per_page - 1) // per_page

    # Calculate page range for pagination
    start_page = max(1, page - 2)
    end_page = min(total_pages + 1, page + 3)
    page_range = range(start_page, end_page)

    return render_template('cache.html',
                           cache_data=cache_data,
                           total=total,
                           page=page,
                           total_pages=total_pages,
                           search=search,
                           per_page=per_page,
                           page_range=page_range)


@app.route('/lookup', methods=['POST'])
def lookup_ip():
    ip = request.json.get('ip')
    if not ip:
        return jsonify({"error": "IP address required"}), 400

    location = get_ip_location(ip)
    return jsonify(location)


@app.route('/upload', methods=['POST'])
def upload_csv():
    files = request.files.getlist('files')
    if not files or files[0].filename == '':
        return Response(f"data: {json.dumps({'type': 'error', 'message': 'No files uploaded'})}\n\n",
                        mimetype='text/event-stream')

    # Read and store file contents upfront
    file_data = []
    for file in files:
        if file.filename.endswith('.csv'):
            try:
                content = file.read()
                file_data.append({'filename': file.filename, 'content': content})
            except:
                file_data.append({'filename': file.filename, 'content': None})

    def generate():
        os.makedirs('results', exist_ok=True)

        total_files = len(file_data)
        total_ips = 0
        processed_ips = 0
        start_time = time.time()

        # Count total IPs
        for file_info in file_data:
            if file_info['content']:
                try:
                    df = pd.read_csv(io.StringIO(file_info['content'].decode('utf-8')))
                    if 'client_ip' in df.columns:
                        total_ips += len(df)
                except:
                    pass

        yield f"data: {json.dumps({'type': 'start', 'total_files': total_files, 'total_ips': total_ips})}\n\n"

        for file_idx, file_info in enumerate(file_data):
            if not file_info['content']:
                yield f"data: {json.dumps({'type': 'file_error', 'filename': file_info['filename'], 'message': 'Failed to read file'})}\n\n"
                continue

            try:
                df = pd.read_csv(io.StringIO(file_info['content'].decode('utf-8')))
                if 'client_ip' not in df.columns:
                    yield f"data: {json.dumps({'type': 'file_error', 'filename': file_info['filename'], 'message': 'Missing client_ip column'})}\n\n"
                    continue

                file_ips = len(df)
                locations = []

                for ip_idx, ip in enumerate(df['client_ip']):
                    location = get_ip_location(str(ip), use_delay=True)
                    locations.append([location['country'], location['region'], location['city']])
                    processed_ips += 1

                    if (ip_idx + 1) % 5 == 0 or ip_idx == file_ips - 1:
                        elapsed = time.time() - start_time
                        rate = processed_ips / elapsed if elapsed > 0 else 0
                        eta = (total_ips - processed_ips) / rate if rate > 0 else 0

                        yield f"data: {json.dumps({
                            'type': 'progress',
                            'file_idx': file_idx + 1,
                            'total_files': total_files,
                            'current_file': file_info['filename'],
                            'file_progress': ip_idx + 1,
                            'file_total': file_ips,
                            'total_progress': processed_ips,
                            'total_ips': total_ips,
                            'percentage': round((processed_ips / total_ips) * 100, 1) if total_ips > 0 else 0,
                            'eta_seconds': round(eta)
                        })}\n\n"

                df[['country', 'region', 'city']] = locations

                output_filename = f"processed_{file_info['filename']}"
                output_path = os.path.join('results', output_filename)
                df.to_csv(output_path, index=False)

                yield f"data: {json.dumps({'type': 'file_complete', 'filename': file_info['filename'], 'status': 'success', 'message': f'Processed {file_ips} IPs'})}\n\n"

            except Exception as e:
                yield f"data: {json.dumps({'type': 'file_complete', 'filename': file_info['filename'], 'status': 'error', 'message': str(e)})}\n\n"

        yield f"data: {json.dumps({'type': 'complete'})}\n\n"

    return Response(generate(), mimetype='text/plain')


@app.route('/results')
def list_results():
    if not os.path.exists('results'):
        return render_template('results.html', files=[])

    files = []
    for filename in os.listdir('results'):
        if filename.endswith('.csv'):
            filepath = os.path.join('results', filename)
            stat = os.stat(filepath)
            files.append({
                'name': filename,
                'size': stat.st_size,
                'modified': stat.st_mtime
            })

    files.sort(key=lambda x: x['modified'], reverse=True)
    return render_template('results.html', files=files)


@app.route('/download/<filename>')
def download_result(filename):
    return send_file(os.path.join('results', filename), as_attachment=True)


@app.route('/delete/<filename>', methods=['POST'])
def delete_result(filename):
    try:
        filepath = os.path.join('results', filename)
        if os.path.exists(filepath):
            os.remove(filepath)
            return jsonify({"success": True})
        return jsonify({"error": "File not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/clean-cache', methods=['POST'])
def clean_cache():
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.execute('DELETE FROM ip_cache')
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/clean-results', methods=['POST'])
def clean_results():
    try:
        if os.path.exists('results'):
            for filename in os.listdir('results'):
                if filename.endswith('.csv'):
                    os.remove(os.path.join('results', filename))
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/fix-cache', methods=['POST'])
def fix_cache():
    try:
        conn = sqlite3.connect(DB_FILE)

        # Get IPs with Unknown or Error data
        cursor = conn.execute(
            "SELECT ip FROM ip_cache WHERE country IN ('Unknown', 'Error') OR region IN ('Unknown', 'Error') OR city IN ('Unknown', 'Error')")
        problem_ips = [row[0] for row in cursor.fetchall()]

        fixed_count = 0
        for ip in problem_ips:
            try:
                response = requests.get(f"http://ip-api.com/json/{ip}", timeout=5)
                data = response.json()

                if data.get("status") == "success":
                    country = data.get("country") or "Unknown"
                    region = data.get("regionName") or "Unknown"
                    city = data.get("city") or "Unknown"

                    # Only update if we got better data
                    if country != "Unknown" or region != "Unknown" or city != "Unknown":
                        conn.execute('UPDATE ip_cache SET country = ?, region = ?, city = ? WHERE ip = ?',
                                     (country, region, city, ip))
                        fixed_count += 1

                time.sleep(0.1)  # Rate limiting
            except:
                continue

        conn.commit()
        conn.close()

        return jsonify({"success": True, "fixed": fixed_count, "total": len(problem_ips)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=8080)
