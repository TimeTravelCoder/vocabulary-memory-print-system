import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import zipfile
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '单词打印系统'))
spec = importlib.util.spec_from_file_location(
    'server', Path(__file__).resolve().parents[1] / '单词打印系统' / 'server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class FakeProcess:
    def __init__(self, stderr=b''):
        self.pid = 424242
        self.returncode = 0
        self.stderr = stderr
        self.killed = False

    def communicate(self, timeout=None):
        return b'', self.stderr

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


class TimeoutProcess(FakeProcess):
    def communicate(self, timeout=None):
        if self.killed:
            return b'', b''
        raise subprocess.TimeoutExpired('edge', timeout or 0)

    def poll(self):
        return None if not self.killed else self.returncode


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.VocabularyHTTPServer(('127.0.0.1', 0), server.VocabularyPrintServer)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.httpd.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()

    def request(self, path, payload=None, headers=None, method=None):
        data = None if payload is None else json.dumps(payload).encode('utf-8')
        request_headers = {'Content-Type': 'application/json'} if data is not None else {}
        request_headers.update(headers or {})
        request = urllib.request.Request(
            self.base + path, data=data, headers=request_headers, method=method)
        try:
            return urllib.request.urlopen(request)
        except urllib.error.HTTPError as error:
            return error

    def wait_http_job(self, job_id):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with self.request('/api/export-jobs/' + job_id) as response:
                status = json.load(response)
            if status['state'] in ('done', 'error', 'cancelled'):
                return status
            time.sleep(0.01)
        self.fail('HTTP job did not finish')

    def test_renderer_isolates_profiles_and_encodes_file_url(self):
        profiles = []
        with tempfile.TemporaryDirectory() as folder:
            html = Path(folder) / '中文 #测试.html'
            pdf = Path(folder) / 'out.pdf'
            html.write_text('<h1>Test</h1>', encoding='utf-8')

            def popen(cmd, **kwargs):
                profiles.append(next(arg for arg in cmd if arg.startswith('--user-data-dir=')))
                self.assertEqual(cmd[-1], html.as_uri())
                pdf.write_bytes(b'%PDF-test')
                return FakeProcess()

            with patch.object(server.subprocess, 'Popen', side_effect=popen):
                server.render_pdf('edge', str(html), str(pdf))
                server.render_pdf('edge', str(html), str(pdf))
        self.assertNotEqual(*profiles)

    def test_renderer_reports_missing_output_and_timeout(self):
        with tempfile.TemporaryDirectory() as folder:
            html = Path(folder) / 'in.html'
            pdf = Path(folder) / 'out.pdf'
            html.write_text('test', encoding='utf-8')
            with patch.object(server.subprocess, 'Popen', return_value=FakeProcess()):
                with self.assertRaisesRegex(RuntimeError, '未生成 PDF'):
                    server.render_pdf('edge', str(html), str(pdf))
            clock = iter((0, 121))
            with patch.object(server.subprocess, 'Popen', return_value=TimeoutProcess()), \
                    patch.object(server.subprocess, 'run'), \
                    patch.object(server.time, 'monotonic', side_effect=lambda: next(clock)):
                with self.assertRaisesRegex(RuntimeError, '超时'):
                    server.render_pdf('edge', str(html), str(pdf))

    def test_html_zip_job_downloads_every_volume(self):
        with self.request('/api/export-jobs', {
            'kind': 'zip', 'format': 'html', 'zipFilename': '词书',
            'volumes': [
                {'filename': '第一册.html', 'html': '<h1>第一册</h1>'},
                {'filename': '第二册.html', 'html': '<h1>第二册</h1>'},
            ],
        }) as response:
            self.assertEqual(response.status, 202)
            job_id = json.load(response)['id']
        self.assertEqual(self.wait_http_job(job_id)['completed'], 2)
        with self.request(f'/api/export-jobs/{job_id}/file') as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), 'application/zip')
            with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
                self.assertEqual(len(archive.namelist()), 2)
                self.assertEqual(archive.read('第二册.html').decode(), '<h1>第二册</h1>')

    def test_data_jobs_download_csv_and_anki_zip(self):
        with self.request('/api/export-jobs', {
            'kind': 'data', 'format': 'csv', 'filename': '学习记录',
            'content': 'word,definition\nhello,你好',
        }) as response:
            self.assertEqual(response.status, 202)
            csv_job = json.load(response)['id']
        self.assertEqual(self.wait_http_job(csv_job)['format'], 'csv')
        with self.request(f'/api/export-jobs/{csv_job}/file') as response:
            self.assertEqual(response.headers.get_content_type(), 'text/csv')
            self.assertIn('filename*=', response.headers['Content-Disposition'])
            self.assertEqual(
                response.read().decode('utf-8-sig'), 'word,definition\nhello,你好')

        with self.request('/api/export-jobs', {
            'kind': 'data-zip', 'format': 'anki', 'filename': '复习包',
            'volumes': [
                {'filename': '../第一组', 'content': 'one\t一'},
                {'filename': '../第一组', 'content': 'two\t二'},
            ],
        }) as response:
            self.assertEqual(response.status, 202)
            zip_job = json.load(response)['id']
        self.assertEqual(self.wait_http_job(zip_job)['completed'], 2)
        with self.request(f'/api/export-jobs/{zip_job}/file') as response:
            self.assertEqual(response.headers.get_content_type(), 'application/zip')
            with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
                self.assertEqual(archive.namelist(), ['_第一组.txt', '_第一组 (2).txt'])
                self.assertEqual(archive.read('_第一组.txt').decode(), 'one\t一')

    def test_data_export_rejects_unsupported_or_missing_content(self):
        for payload in (
                {'kind': 'data', 'format': 'pdf', 'content': 'bad'},
                {'kind': 'data', 'format': 'csv'},
                {'kind': 'data-zip', 'format': 'pdf', 'volumes': [
                    {'content': 'bad'},
                ]}):
            with self.request('/api/export-jobs', payload) as response:
                self.assertEqual(response.status, 400)
                self.assertTrue(json.load(response)['error'])

    def test_mutating_api_rejects_cross_site_and_non_json_requests(self):
        headers = {'Origin': 'https://attacker.example', 'Content-Type': 'text/plain'}
        with self.request('/api/export-jobs', {'kind': 'zip', 'volumes': []}, headers) as response:
            self.assertEqual(response.status, 403)
        with self.request('/api/export-jobs', {'kind': 'zip', 'volumes': []}, {
                'Content-Type': 'text/plain'}) as response:
            self.assertEqual(response.status, 415)
        with self.request('/api/export-pdf', {'html': 'test'}) as response:
            self.assertEqual(response.status, 404)

    def test_book_endpoint_rejects_traversal_and_cross_drive(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder) / 'books'
            sibling = Path(folder) / 'books-private'
            data.mkdir()
            sibling.mkdir()
            (sibling / 'secret.json').write_text('[]')
            with patch.object(server, 'DATA_DIR', str(data)):
                with self.request('/api/book?path=../books-private/secret.json') as response:
                    self.assertEqual(response.status, 403)
                if os.name == 'nt':
                    with self.request('/api/book?path=C:%5CWindows%5Cwin.ini') as response:
                        self.assertEqual(response.status, 403)

    def test_static_assets_avoid_stale_frontend_cache(self):
        with self.request('/index.html') as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get('Cache-Control'), 'no-store')
            html = response.read().decode('utf-8')
        self.assertIn('advanced_features.js?v=20261018', html)
        self.assertIn('workbench.js?v=20261018', html)
        with self.request('/workbench.js?v=20261018') as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get('Cache-Control'), 'no-store')


if __name__ == '__main__':
    unittest.main()
