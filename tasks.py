import io
import os
import time
import pandas as pd
from rq import get_current_job

from app import get_ip_location


def process_csv_job(file_data):
    """Background job to process uploaded CSV files."""
    job = get_current_job()
    os.makedirs('results', exist_ok=True)

    total_files = len(file_data)
    total_ips = 0
    for info in file_data:
        if info['content']:
            try:
                df = pd.read_csv(io.StringIO(info['content'].decode('utf-8')))
                if 'client_ip' in df.columns:
                    total_ips += len(df)
            except Exception:
                pass

    job.meta['start'] = {'type': 'start', 'total_files': total_files, 'total_ips': total_ips}
    job.save_meta()

    processed_ips = 0
    start_time = time.time()
    results = []

    for file_idx, file_info in enumerate(file_data):
        if not file_info['content']:
            results.append({'type': 'file_error', 'filename': file_info['filename'], 'message': 'Failed to read file'})
            continue

        try:
            df = pd.read_csv(io.StringIO(file_info['content'].decode('utf-8')))
            if 'client_ip' not in df.columns:
                results.append({'type': 'file_error', 'filename': file_info['filename'], 'message': 'Missing client_ip column'})
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
                    job.meta['progress'] = {
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
                    }
                    job.save_meta()

            df[['country', 'region', 'city']] = locations
            output_filename = f"processed_{file_info['filename']}"
            output_path = os.path.join('results', output_filename)
            df.to_csv(output_path, index=False)
            results.append({'type': 'file_complete', 'filename': file_info['filename'], 'status': 'success', 'message': f'Processed {file_ips} IPs'})

        except Exception as e:
            results.append({'type': 'file_complete', 'filename': file_info['filename'], 'status': 'error', 'message': str(e)})

    job.meta['results'] = results
    job.meta['complete'] = True
    job.save_meta()
    return True
