import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import urllib.parse
import webbrowser

from export_jobs import ExportBusyError, ExportConflictError, ExportJobs


def _stop_process_tree(process):
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(
            ['taskkill', '/PID', str(process.pid), '/T', '/F'],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    if process.poll() is None:
        process.kill()
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()


def render_pdf(browser_path, html_path, pdf_path, cancel_event=None):
    """Render one local HTML document and always reap its browser process tree."""
    cancel_event = cancel_event or threading.Event()
    with tempfile.TemporaryDirectory(prefix='vocab_browser_') as profile:
        cmd = [
            browser_path, '--headless=new', '--disable-gpu', '--disable-extensions',
            '--disable-background-networking', '--no-first-run',
            '--no-default-browser-check', f'--user-data-dir={profile}',
            '--no-pdf-header-footer', f'--print-to-pdf={pdf_path}',
            Path(html_path).as_uri(),
        ]
        options = {
            'stdout': subprocess.PIPE,
            'stderr': subprocess.PIPE,
        }
        if os.name == 'nt':
            options['creationflags'] = subprocess.CREATE_NO_WINDOW
        else:
            options['start_new_session'] = True
        process = subprocess.Popen(cmd, **options)
        started = time.monotonic()
        result = None
        try:
            while True:
                if cancel_event.is_set():
                    raise InterruptedError('已取消导出')
                if time.monotonic() - started > 120:
                    raise subprocess.TimeoutExpired(cmd, 120)
                try:
                    stdout, stderr = process.communicate(timeout=0.2)
                    result = subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
                    break
                except subprocess.TimeoutExpired:
                    continue
        except subprocess.TimeoutExpired as error:
            raise RuntimeError('PDF 生成超时，请减少每卷页数后重试') from error
        finally:
            _stop_process_tree(process)

        if not os.path.isfile(pdf_path) or os.path.getsize(pdf_path) == 0:
            detail = (result.stderr if result else b'').decode('utf-8', errors='replace')[-500:]
            raise RuntimeError('浏览器未生成 PDF，请重试。' + detail)
        with open(pdf_path, 'rb') as pdf:
            if pdf.read(5) != b'%PDF-':
                raise RuntimeError('浏览器生成的文件不是有效 PDF')


SYSTEM_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(os.path.join(os.path.dirname(SYSTEM_DIR), '中英合并释义_JSON')):
    DATA_DIR = os.path.join(os.path.dirname(SYSTEM_DIR), '中英合并释义_JSON')
elif os.path.exists(os.path.join(SYSTEM_DIR, '中英合并释义_JSON')):
    DATA_DIR = os.path.join(SYSTEM_DIR, '中英合并释义_JSON')
else:
    DATA_DIR = os.path.join(os.path.dirname(SYSTEM_DIR), '中英合并释义_JSON')


def find_browser_path():
    candidates = [
        shutil.which('msedge'), shutil.which('chrome'), shutil.which('chromium'),
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
        os.path.expanduser(r'~\AppData\Local\Microsoft\Edge\Application\msedge.exe'),
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        os.path.expanduser(r'~\AppData\Local\Google\Chrome\Application\chrome.exe'),
    ]
    return next((path for path in candidates if path and os.path.isfile(path)), None)


EXPORT_JOBS = ExportJobs(render_pdf, find_browser_path)


class ApiRequestError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class VocabularyPrintServer(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SYSTEM_DIR, **kwargs)

    def log_message(self, format, *args):
        sys.stdout.write(f'[{self.log_date_time_string()}] {format % args}\n')
        sys.stdout.flush()

    def send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(data)

    def _same_origin_request(self):
        if self.headers.get('Sec-Fetch-Site', '').lower() == 'cross-site':
            return False
        origin = self.headers.get('Origin')
        if not origin:
            return True
        try:
            parsed = urllib.parse.urlsplit(origin)
            host_ok = parsed.hostname in ('127.0.0.1', 'localhost', '::1')
            return parsed.scheme in ('http', 'https') and host_ok and parsed.port == self.server.server_port
        except ValueError:
            return False

    def _read_json(self, maximum=100 * 1024 * 1024):
        if not self._same_origin_request():
            raise ApiRequestError(403, '拒绝跨站请求')
        content_type = self.headers.get_content_type().lower()
        if content_type != 'application/json':
            raise ApiRequestError(415, '请求必须使用 application/json')
        try:
            size = int(self.headers.get('Content-Length', ''))
        except ValueError as error:
            raise ApiRequestError(411, '缺少有效的 Content-Length') from error
        if size < 1:
            raise ApiRequestError(400, '请求内容为空')
        if size > maximum:
            raise ApiRequestError(413, '排版内容过大，请减小分卷范围')
        try:
            payload = json.loads(self.rfile.read(size).decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ApiRequestError(400, 'JSON 格式无效') from error
        if not isinstance(payload, dict):
            raise ApiRequestError(400, '请求内容必须是 JSON 对象')
        return payload

    def do_OPTIONS(self):
        self.send_response(405)
        self.send_header('Allow', 'GET, POST')
        self.send_header('Connection', 'close')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        job_match = re.fullmatch(r'/api/export-jobs/([a-f0-9]{32})(/file)?', path)
        if job_match:
            job_id, wants_file = job_match.group(1), bool(job_match.group(2))
            status = EXPORT_JOBS.status(job_id)
            if not status:
                return self.send_json(404, {'error': '任务不存在或已过期'})
            if not wants_file:
                return self.send_json(200, status)
            if status['state'] != 'done':
                return self.send_json(409, {'error': '文件尚未生成或任务已取消'})
            artifact = EXPORT_JOBS.file(job_id)
            if not artifact:
                return self.send_json(410, {'error': '导出文件已过期，请重新生成'})
            self.send_response(200)
            self.send_header('Content-Type', artifact['mime'])
            self.send_header('Content-Length', str(artifact['size']))
            self.send_header(
                'Content-Disposition',
                "attachment; filename*=UTF-8''" + urllib.parse.quote(artifact['filename']))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Connection', 'close')
            self.end_headers()
            try:
                with artifact['path'].open('rb') as source:
                    shutil.copyfileobj(source, self.wfile, length=1024 * 1024)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        if path == '/api/catalog':
            catalog_path = Path(SYSTEM_DIR) / 'catalog.json'
            if not catalog_path.is_file():
                return self.send_error(404, 'Catalog not found')
            data = catalog_path.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(data)
            return

        if path == '/api/book':
            rel_path = query.get('path', [''])[0]
            if not rel_path:
                return self.send_error(400, 'Missing path param')
            root = os.path.realpath(DATA_DIR)
            relative = urllib.parse.unquote(rel_path).replace('/', os.sep).replace('\\', os.sep).lstrip(os.sep)
            candidate = os.path.realpath(os.path.join(root, relative))
            try:
                allowed = os.path.commonpath([candidate, root]) == root
            except (ValueError, OSError):
                allowed = False
            if not allowed:
                return self.send_error(403, 'Access denied')
            if not os.path.isfile(candidate) or not candidate.lower().endswith('.json'):
                return self.send_error(404, 'Book file not found')
            data = Path(candidate).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(data)
            return

        if path in ('/', ''):
            self.send_response(302)
            self.send_header('Location', '/index.html')
            self.send_header('Connection', 'close')
            self.end_headers()
            return
        super().do_GET()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == '/api/export-jobs':
                payload = self._read_json()
                try:
                    job_id = EXPORT_JOBS.create(payload)
                except ExportConflictError as error:
                    return self.send_json(409, {'error': str(error)})
                except ExportBusyError as error:
                    return self.send_json(429, {'error': str(error)})
                except ValueError as error:
                    return self.send_json(400, {'error': str(error)})
                return self.send_json(202, {'id': job_id})

            cancel_match = re.fullmatch(r'/api/export-jobs/([a-f0-9]{32})/cancel', path)
            if cancel_match:
                self._read_json(maximum=1024)
                state = EXPORT_JOBS.cancel(cancel_match.group(1))
                if state is None:
                    return self.send_json(404, {'error': '任务不存在'})
                return self.send_json(202 if state in ('queued', 'running') else 200, {
                    'state': 'cancelling' if state in ('queued', 'running') else state,
                })
        except ApiRequestError as error:
            return self.send_json(error.status, {'error': str(error)})
        self.send_error(404, 'Endpoint not found')


class VocabularyHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def create_server(start_port=8899, attempts=50):
    last_error = None
    for port in range(start_port, start_port + attempts):
        try:
            return VocabularyHTTPServer(('127.0.0.1', port), VocabularyPrintServer)
        except OSError as error:
            last_error = error
    raise RuntimeError(f'无法在 {start_port} 到 {start_port + attempts - 1} 端口启动服务') from last_error


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    httpd = create_server()
    port = httpd.server_port
    url = f'http://127.0.0.1:{port}/index.html'

    print('=' * 60, flush=True)
    print('  [OK] 单词打印记忆本系统已成功启动！', flush=True)
    print(f'  服务网址: {url}', flush=True)
    print('  （浏览器已自动打开，若未打开请手动复制上方网址打开）', flush=True)
    print('  请勿关闭此黑色窗口，按 Ctrl + C 可退出服务', flush=True)
    print('=' * 60, flush=True)

    opener = threading.Timer(0.5, lambda: webbrowser.open(url))
    opener.daemon = True
    opener.start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n系统已退出。', flush=True)
    finally:
        httpd.server_close()
        EXPORT_JOBS.shutdown()


if __name__ == '__main__':
    main()
