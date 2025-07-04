from flask import Flask, render_template, request, jsonify, send_file, Response, redirect, url_for
import pandas as pd
import requests
import sqlite3
import io
import os
import time
import json
import csv
import pymysql
from dotenv import load_dotenv

app = Flask(__name__)

# Load configuration from .env file if present
load_dotenv()

# Configuration with defaults
DB_FILE = os.getenv("DB_FILE", "ip_cache.db")
PORT = int(os.getenv("PORT", "8080"))
DEBUG = os.getenv("DEBUG", "True").lower() == "true"

# Dynamic classification thresholds
HIGH_TRAFFIC_THRESHOLD = int(os.getenv("HIGH_TRAFFIC_THRESHOLD", "100"))
SUBNET_IP_THRESHOLD = int(os.getenv("SUBNET_IP_THRESHOLD", "50"))
SUBNET_VIEW_THRESHOLD = int(os.getenv("SUBNET_VIEW_THRESHOLD", "5000"))


@app.template_filter('timestamp_to_date')
def timestamp_to_date(timestamp):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))


# Initialize database
def init_db():
    """Create the cache table and add any missing columns."""
    conn = sqlite3.connect(DB_FILE)

    # Base table with only the primary key to allow incremental upgrades
    conn.execute("CREATE TABLE IF NOT EXISTS ip_cache (ip TEXT PRIMARY KEY)")

    # Table for stored MySQL connection info
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mysql_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            host TEXT NOT NULL,
            port INTEGER NOT NULL,
            user TEXT NOT NULL,
            password TEXT NOT NULL,
            database TEXT NOT NULL
        )
        """
    )

    # List of required columns and their SQLite types
    required_columns = {
        "status": "TEXT",
        "continent": "TEXT",
        "continentCode": "TEXT",
        "country": "TEXT",
        "countryCode": "TEXT",
        "region": "TEXT",
        "regionCode": "TEXT",
        "city": "TEXT",
        "district": "TEXT",
        "zip": "TEXT",
        "lat": "REAL",
        "lon": "REAL",
        "timezone": "TEXT",
        "offset": "INTEGER",
        "currency": "TEXT",
        "isp": "TEXT",
        "org": "TEXT",
        "as": "TEXT",
        "asname": "TEXT",
        "mobile": "INTEGER",
        "proxy": "INTEGER",
        "hosting": "INTEGER",
    }

    cursor = conn.execute("PRAGMA table_info(ip_cache)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    # Add any missing columns
    for column, col_type in required_columns.items():
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE ip_cache ADD COLUMN \"{column}\" {col_type}")

    conn.commit()
    conn.close()


init_db()


def get_ip_location(ip, use_delay=False):
    """Retrieve IP information, using the cache when possible."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute('SELECT * FROM ip_cache WHERE ip = ?', (ip,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return dict(row)

    if use_delay:
        time.sleep(0.5)  # Rate limiting

    # Retry logic with exponential backoff
    for attempt in range(3):
        try:
            response = requests.get(f"http://ip-api.com/json/{ip}", timeout=15)

            if response.status_code == 429:  # Rate limited
                time.sleep(2 ** attempt)
                continue

            data = response.json()

            if data.get("status") == "success":
                result = {
                    "ip": ip,
                    "status": data.get("status"),
                    "continent": data.get("continent", "Unknown"),
                    "continentCode": data.get("continentCode", "Unknown"),
                    "country": data.get("country", "Unknown"),
                    "countryCode": data.get("countryCode", "Unknown"),
                    "region": data.get("regionName", "Unknown"),
                    "regionCode": data.get("region", ""),
                    "city": data.get("city", "Unknown"),
                    "district": data.get("district", ""),
                    "zip": data.get("zip", ""),
                    "lat": data.get("lat"),
                    "lon": data.get("lon"),
                    "timezone": data.get("timezone", ""),
                    "offset": data.get("offset"),
                    "currency": data.get("currency", ""),
                    "isp": data.get("isp", ""),
                    "org": data.get("org", ""),
                    "as": data.get("as", ""),
                    "asname": data.get("asname", ""),
                    "mobile": int(data.get("mobile", 0)),
                    "proxy": int(data.get("proxy", 0)),
                    "hosting": int(data.get("hosting", 0)),
                }
                break
            else:
                result = {
                    "ip": ip,
                    "status": data.get("status", "fail"),
                    "continent": "Unknown",
                    "continentCode": "Unknown",
                    "country": "Unknown",
                    "countryCode": "Unknown",
                    "region": "Unknown",
                    "regionCode": "",
                    "city": "Unknown",
                    "district": "",
                    "zip": "",
                    "lat": None,
                    "lon": None,
                    "timezone": "",
                    "offset": None,
                    "currency": "",
                    "isp": "",
                    "org": "",
                    "as": "",
                    "asname": "",
                    "mobile": 0,
                    "proxy": 0,
                    "hosting": 0,
                }
                break
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.RequestException):
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            result = {
                "ip": ip,
                "status": "error",
                "continent": "Network Error",
                "continentCode": "Network Error",
                "country": "Network Error",
                "countryCode": "Network Error",
                "region": "Network Error",
                "regionCode": "",
                "city": "Network Error",
                "district": "",
                "zip": "",
                "lat": None,
                "lon": None,
                "timezone": "",
                "offset": None,
                "currency": "",
                "isp": "",
                "org": "",
                "as": "",
                "asname": "",
                "mobile": 0,
                "proxy": 0,
                "hosting": 0,
            }
        except Exception:
            result = {
                "ip": ip,
                "status": "error",
                "continent": "Error",
                "continentCode": "Error",
                "country": "Error",
                "countryCode": "Error",
                "region": "Error",
                "regionCode": "",
                "city": "Error",
                "district": "",
                "zip": "",
                "lat": None,
                "lon": None,
                "timezone": "",
                "offset": None,
                "currency": "",
                "isp": "",
                "org": "",
                "as": "",
                "asname": "",
                "mobile": 0,
                "proxy": 0,
                "hosting": 0,
            }
            break

    # Save full response to cache
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        """
        INSERT OR REPLACE INTO ip_cache (
            ip, status, continent, continentCode, country, countryCode,
            region, regionCode, city, district, zip, lat, lon, timezone,
            offset, currency, isp, org, "as", asname, mobile, proxy, hosting
        ) VALUES (
            :ip, :status, :continent, :continentCode, :country, :countryCode,
            :region, :regionCode, :city, :district, :zip, :lat, :lon, :timezone,
            :offset, :currency, :isp, :org, :as, :asname, :mobile, :proxy, :hosting
        )
        """,
        result,
    )
    conn.commit()
    conn.close()

    return result


@app.route('/')
def index():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    connections = conn.execute(
        'SELECT id, name, database FROM mysql_connections'
    ).fetchall()
    conn.close()
    return render_template('index.html', mysql_connections=connections)


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
    # Limit results to 15 rows per page for easier browsing
    per_page = 15
    search = request.args.get('search', '').strip()
    country_filter = request.args.get('country', '').strip()
    region_filter = request.args.get('region', '').strip()
    city_filter = request.args.get('city', '').strip()

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row

    where_clauses = []
    params = []

    if search:
        where_clauses.append('(ip LIKE ? OR country LIKE ? OR region LIKE ? OR city LIKE ?)')
        term = f'%{search}%'
        params.extend([term, term, term, term])
    if country_filter:
        where_clauses.append('country = ?')
        params.append(country_filter)
    if region_filter:
        where_clauses.append('region = ?')
        params.append(region_filter)
    if city_filter:
        where_clauses.append('city = ?')
        params.append(city_filter)

    where_sql = 'WHERE ' + ' AND '.join(where_clauses) if where_clauses else ''

    query = f'SELECT ip, country, region, city, lat, lon, isp, timezone FROM ip_cache {where_sql} ORDER BY ip LIMIT ? OFFSET ?'
    params_with_limit = params + [per_page, (page - 1) * per_page]
    cursor = conn.execute(query, params_with_limit)

    count_query = f'SELECT COUNT(*) FROM ip_cache {where_sql}'
    count_cursor = conn.execute(count_query, params)
    total = count_cursor.fetchone()[0]

    # Unique values for filters
    countries = [row[0] for row in conn.execute('SELECT DISTINCT country FROM ip_cache WHERE country != "" ORDER BY country').fetchall()]
    regions = [row[0] for row in conn.execute('SELECT DISTINCT region FROM ip_cache WHERE region != "" ORDER BY region').fetchall()]
    cities = [row[0] for row in conn.execute('SELECT DISTINCT city FROM ip_cache WHERE city != "" ORDER BY city').fetchall()]

    cache_data = [dict(row) for row in cursor.fetchall()]
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
                           country_filter=country_filter,
                           region_filter=region_filter,
                           city_filter=city_filter,
                           countries=countries,
                           regions=regions,
                           cities=cities,
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


@app.route('/connections', methods=['GET', 'POST'])
def manage_connections():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    if request.method == 'POST':
        data = request.form
        conn.execute(
            'INSERT INTO mysql_connections (name, host, port, user, password, database) VALUES (?,?,?,?,?,?)',
            (
                data.get('name'),
                data.get('host'),
                int(data.get('port', 3306)),
                data.get('user'),
                data.get('password'),
                data.get('database'),
            ),
        )
        conn.commit()

    rows = conn.execute(
        'SELECT id, name, host, port, user, database FROM mysql_connections'
    ).fetchall()
    conn.close()
    return render_template('connections.html', connections=rows)


@app.route('/connections/delete/<int:conn_id>', methods=['POST'])
def delete_connection(conn_id):
    conn = sqlite3.connect(DB_FILE)
    conn.execute('DELETE FROM mysql_connections WHERE id=?', (conn_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('manage_connections'))


@app.route('/fetch-mysql', methods=['POST'])
def fetch_mysql():
    data = request.get_json()
    connection_id = data.get('connection_id')
    table = data.get('table')
    ip_column = data.get('ip_column', 'client_ip')

    if not connection_id or not table:
        return Response(
            f"data: {json.dumps({'type': 'error', 'message': 'Missing parameters'})}\n\n",
            mimetype='text/event-stream',
        )

    def generate():
        db_conn = sqlite3.connect(DB_FILE)
        db_conn.row_factory = sqlite3.Row
        row = db_conn.execute(
            'SELECT * FROM mysql_connections WHERE id=?', (connection_id,)
        ).fetchone()
        db_conn.close()
        if not row:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Connection not found'})}\n\n"
            return

        try:
            mysql_db = pymysql.connect(
                host=row['host'],
                port=row['port'],
                user=row['user'],
                password=row['password'],
                database=row['database'],
                cursorclass=pymysql.cursors.Cursor,
            )
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        cur = mysql_db.cursor()
        try:
            cur.execute(f'SELECT {ip_column} FROM {table}')
            ips = [str(r[0]) for r in cur.fetchall()]
        except Exception as e:
            mysql_db.close()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return
        mysql_db.close()

        total_ips = len(ips)
        processed = 0
        os.makedirs('results', exist_ok=True)
        filename = f"mysql_{table}_{int(time.time())}.csv"
        filepath = os.path.join('results', filename)

        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['client_ip', 'country', 'region', 'city'])
            for ip in ips:
                location = get_ip_location(ip, use_delay=True)
                writer.writerow([ip, location['country'], location['region'], location['city']])
                processed += 1
                if processed % 5 == 0 or processed == total_ips:
                    yield f"data: {json.dumps({'type': 'progress', 'processed': processed, 'total': total_ips})}\n\n"

        yield f"data: {json.dumps({'type': 'complete', 'filename': filename})}\n\n"

    return Response(generate(), mimetype='text/event-stream')


@app.route('/view/<filename>')
def view_result(filename):
    filepath = os.path.join('results', filename)
    if not os.path.exists(filepath):
        return 'File not found', 404
    try:
        df = pd.read_csv(filepath)
    except Exception as e:
        return str(e), 500
    dynamic_counts = None
    classification_rules = None

    if {'client_ip', 'ip_count'}.issubset(df.columns):
        df['subnet_24'] = df['client_ip'].astype(str).apply(lambda x: '.'.join(x.split('.')[:3]))


        subnet_stats = df.groupby('subnet_24').agg(
            ip_count=('client_ip', 'count'),
            total_views=('ip_count', 'sum')
        ).reset_index()

        suspicious_subnets = subnet_stats[
            (subnet_stats['ip_count'] > SUBNET_IP_THRESHOLD) &
            (subnet_stats['total_views'] > SUBNET_VIEW_THRESHOLD)
        ]['subnet_24'].tolist()

        def classify_dynamic(row):
            if row['ip_count'] >= HIGH_TRAFFIC_THRESHOLD:
                return 'likely_fake'
            if row['subnet_24'] in suspicious_subnets:
                return 'likely_fake'
            return 'likely_real'

        df['dynamic_classification'] = df.apply(classify_dynamic, axis=1)

        summary = df.groupby('dynamic_classification')['ip_count'].agg(['count', 'sum']).reset_index()
        summary.columns = ['classification', 'ip_address_count', 'total_views']
        dynamic_counts = summary.set_index('classification').to_dict(orient='index')

        classification_rules = [
            f"Likely fake if IP count >= {HIGH_TRAFFIC_THRESHOLD}",
            f"Likely fake if subnet has > {SUBNET_IP_THRESHOLD} IPs and > {SUBNET_VIEW_THRESHOLD} total views",
            "Otherwise likely real",
        ]

        df.drop(columns=['subnet_24'], inplace=True)

    records = df.to_dict(orient='records')
    columns = [c for c in df.columns if c != 'dynamic_classification']

    return render_template(
        'view.html',
        filename=filename,
        records=records,
        columns=columns,
        dynamic_counts=dynamic_counts,
        classification_rules=classification_rules
    )


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


@app.route('/delete-cache/<ip>', methods=['POST'])
def delete_cache_ip(ip):
    """Delete a single IP entry from the cache."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.execute('DELETE FROM ip_cache WHERE ip = ?', (ip,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
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
                    result = {
                        "ip": ip,
                        "status": data.get("status"),
                        "continent": data.get("continent", "Unknown"),
                        "continentCode": data.get("continentCode", "Unknown"),
                        "country": data.get("country", "Unknown"),
                        "countryCode": data.get("countryCode", "Unknown"),
                        "region": data.get("regionName", "Unknown"),
                        "regionCode": data.get("region", ""),
                        "city": data.get("city", "Unknown"),
                        "district": data.get("district", ""),
                        "zip": data.get("zip", ""),
                        "lat": data.get("lat"),
                        "lon": data.get("lon"),
                        "timezone": data.get("timezone", ""),
                        "offset": data.get("offset"),
                        "currency": data.get("currency", ""),
                        "isp": data.get("isp", ""),
                        "org": data.get("org", ""),
                        "as": data.get("as", ""),
                        "asname": data.get("asname", ""),
                        "mobile": int(data.get("mobile", 0)),
                        "proxy": int(data.get("proxy", 0)),
                        "hosting": int(data.get("hosting", 0)),
                    }

                    # Only update if we got better data
                    if result["country"] != "Unknown" or result["region"] != "Unknown" or result["city"] != "Unknown":
                        conn.execute(
                            """
                            UPDATE ip_cache SET
                                status=:status, continent=:continent, continentCode=:continentCode,
                                country=:country, countryCode=:countryCode, region=:region,
                                regionCode=:regionCode, city=:city, district=:district,
                                zip=:zip, lat=:lat, lon=:lon, timezone=:timezone, offset=:offset,
                                currency=:currency, isp=:isp, org=:org, "as"=:as, asname=:asname,
                                mobile=:mobile, proxy=:proxy, hosting=:hosting
                            WHERE ip=:ip
                            """,
                            result,
                        )
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
    app.run(debug=DEBUG, port=PORT)
