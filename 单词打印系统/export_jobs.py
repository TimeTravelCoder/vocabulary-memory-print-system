"""Bounded FIFO export jobs with progress, cancellation, and disk-backed results."""
from collections import deque
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
import unicodedata
import uuid
import zipfile


class ExportBusyError(RuntimeError):
    """Raised when the export queue has reached its configured limit."""


class ExportConflictError(RuntimeError):
    """Raised when a client tries to reuse an existing job id."""


class ExportJobs:
    FORMAT_SPECS = {
        'pdf': ('.pdf', 'application/pdf'),
        'html': ('.html', 'text/html; charset=utf-8'),
        'csv': ('.csv', 'text/csv; charset=utf-8'),
        'tsv': ('.tsv', 'text/tab-separated-values; charset=utf-8'),
        'anki': ('.txt', 'text/plain; charset=utf-8'),
        'txt': ('.txt', 'text/plain; charset=utf-8'),
    }
    DATA_FORMATS = frozenset(('csv', 'tsv', 'anki', 'txt'))
    MAX_VOLUMES = 1000
    MAX_ITEM_BYTES = 25 * 1024 * 1024
    MAX_TOTAL_BYTES = 100 * 1024 * 1024
    WINDOWS_RESERVED_NAMES = frozenset({
        'CON', 'PRN', 'AUX', 'NUL',
        *(f'COM{index}' for index in range(1, 10)),
        *(f'LPT{index}' for index in range(1, 10)),
    })

    def __init__(self, renderer, browser_finder, retention_seconds=1800,
                 max_finished=20, max_workers=2, max_pending=20,
                 max_queued_bytes=200 * 1024 * 1024):
        if max_workers < 1 or max_pending < max_workers or max_queued_bytes < 1:
            raise ValueError('导出并发和队列限制无效')
        self.renderer = renderer
        self.browser_finder = browser_finder
        self.retention_seconds = retention_seconds
        self.max_finished = max_finished
        self.max_workers = max_workers
        self.max_pending = max_pending
        self.max_queued_bytes = max_queued_bytes
        self.jobs = {}
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.pending = deque()
        self._temp = tempfile.TemporaryDirectory(prefix='vocab_exports_')
        self.output_dir = Path(self._temp.name)
        self.closed = False
        self.threads = {
            threading.Thread(
                target=self._worker, name=f'vocab-export-worker-{index + 1}', daemon=True)
            for index in range(max_workers)
        }
        for thread in self.threads:
            thread.start()

    @staticmethod
    def safe_name(value):
        name = unicodedata.normalize('NFC', str(value or ''))
        name = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', '_', name).strip(' .')[:180]
        if not name:
            return 'vocabulary'
        if name.split('.', 1)[0].upper() in ExportJobs.WINDOWS_RESERVED_NAMES:
            name = '_' + name
        return name

    @staticmethod
    def _with_extension(value, extension):
        name = ExportJobs.safe_name(value)
        if not name.lower().endswith(extension):
            name += extension
        return name

    @staticmethod
    def _unique_name(filename, used_names):
        key = filename.casefold()
        if key not in used_names:
            used_names.add(key)
            return filename
        suffix = Path(filename).suffix
        stem = filename[:-len(suffix)] if suffix else filename
        counter = 2
        while True:
            tail = f' ({counter}){suffix}'
            candidate = stem[:max(1, 180 - len(tail))] + tail
            key = candidate.casefold()
            if key not in used_names:
                used_names.add(key)
                return candidate
            counter += 1

    @classmethod
    def _format_content(cls, volume, fmt):
        key = 'html' if fmt in ('pdf', 'html') else 'content'
        content = volume.get(key)
        if content is None and key == 'content':
            content = volume.get('text')
        if not isinstance(content, str) or not content.strip():
            label = 'HTML 排版内容' if key == 'html' else '文本导出内容'
            raise ValueError(f'缺少有效的{label}')
        return content

    @classmethod
    def _normalise_request(cls, payload):
        if not isinstance(payload, dict):
            raise ValueError('请求内容必须是 JSON 对象')
        kind = payload.get('kind')
        if kind not in ('pdf', 'data', 'zip', 'data-zip'):
            raise ValueError('不支持的任务类型')

        if kind == 'pdf':
            if payload.get('format', 'pdf') != 'pdf':
                raise ValueError('PDF 任务不支持其他导出格式')
            default_format = 'pdf'
            allowed_formats = ('pdf',)
            source_volumes = [payload]
        elif kind == 'data':
            default_format = payload.get('format', 'txt')
            if default_format not in cls.DATA_FORMATS:
                raise ValueError('单文件数据导出仅支持 CSV、TSV、Anki 或 TXT')
            allowed_formats = cls.DATA_FORMATS
            source_volumes = [payload]
        else:
            data_zip = kind == 'data-zip'
            default_format = payload.get('format', 'txt' if data_zip else 'pdf')
            allowed_formats = cls.DATA_FORMATS if data_zip else cls.FORMAT_SPECS
            if default_format not in allowed_formats:
                raise ValueError('不支持的 ZIP 内容格式')
            source_volumes = payload.get('volumes')
            kind = 'zip'

        if (not isinstance(source_volumes, list) or not source_volumes or
                len(source_volumes) > cls.MAX_VOLUMES):
            raise ValueError(f'没有有效的导出内容，或分卷数量超过 {cls.MAX_VOLUMES}')

        volumes = []
        total_size = 0
        for index, volume in enumerate(source_volumes):
            if not isinstance(volume, dict):
                raise ValueError(f'第 {index + 1} 个分卷无效')
            fmt = volume.get('format', default_format) if kind == 'zip' else default_format
            if fmt not in allowed_formats:
                raise ValueError(f'第 {index + 1} 个分卷格式不受支持')
            content = cls._format_content(volume, fmt)
            size = len(content.encode('utf-8'))
            if size > cls.MAX_ITEM_BYTES:
                raise ValueError(f'第 {index + 1} 个分卷超过 25 MB')
            total_size += size
            if total_size > cls.MAX_TOTAL_BYTES:
                raise ValueError('导出内容总计超过 100 MB')
            volumes.append({
                'format': fmt,
                'content': content,
                'filename': volume.get('filename', f'volume_{index + 1}'),
            })
        return kind, volumes, total_size

    @staticmethod
    def _encode_text(content, fmt):
        # A UTF-8 BOM makes CSV/TSV open correctly in common Windows spreadsheet apps.
        if fmt in ('csv', 'tsv'):
            return content.removeprefix('\ufeff').encode('utf-8-sig')
        return content.encode('utf-8')

    def _remove_job_locked(self, job_id):
        job = self.jobs.pop(job_id, None)
        if not job:
            return
        path = job.get('path')
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass

    def _cleanup_locked(self):
        now = time.time()
        terminal = ('done', 'error', 'cancelled')
        for job_id, job in list(self.jobs.items()):
            if job['state'] in terminal and now - job['updated'] > self.retention_seconds:
                self._remove_job_locked(job_id)
        finished = sorted(
            (job for job in self.jobs.values() if job['state'] in terminal),
            key=lambda job: job['updated'], reverse=True)
        for job in finished[self.max_finished:]:
            self._remove_job_locked(job['id'])

    def create(self, payload):
        kind, volumes, input_bytes = self._normalise_request(payload)
        job_id = payload.get('id') or uuid.uuid4().hex
        if not isinstance(job_id, str) or not re.fullmatch(r'[a-f0-9]{32}', job_id):
            raise ValueError('任务编号无效')

        if kind == 'zip':
            extension, mime = '.zip', 'application/zip'
            requested_name = payload.get(
                'zipFilename', payload.get('filename', 'vocabulary.zip'))
        else:
            extension, mime = self.FORMAT_SPECS[volumes[0]['format']]
            requested_name = payload.get('filename', 'vocabulary' + extension)
        job = {
            'id': job_id, 'state': 'queued', 'completed': 0, 'total': len(volumes),
            'error': '', 'cancel': threading.Event(), 'updated': time.time(),
            'path': None, 'size': 0,
            'filename': self._with_extension(requested_name, extension),
            'mime': mime,
            'format': 'zip' if kind == 'zip' else volumes[0]['format'],
            'inputBytes': input_bytes,
        }

        with self.condition:
            self._cleanup_locked()
            if self.closed:
                raise ExportBusyError('导出服务正在关闭')
            if job_id in self.jobs:
                raise ExportConflictError('任务编号重复')
            active = sum(
                existing['state'] in ('queued', 'running') for existing in self.jobs.values())
            if active >= self.max_pending:
                raise ExportBusyError(f'导出队列已满（最多 {self.max_pending} 个任务）')
            queued_bytes = sum(
                existing['inputBytes'] for existing in self.jobs.values()
                if existing['state'] in ('queued', 'running'))
            if queued_bytes + input_bytes > self.max_queued_bytes:
                raise ExportBusyError('导出队列内容过大，请等待现有任务完成后重试')
            self.jobs[job_id] = job
            self.pending.append((job, volumes, kind))
            self.condition.notify()
        return job_id

    def _worker(self):
        while True:
            with self.condition:
                while not self.pending and not self.closed:
                    self.condition.wait()
                if self.closed and not self.pending:
                    return
                job, volumes, kind = self.pending.popleft()
                if job['cancel'].is_set():
                    job['state'] = 'cancelled'
                    job['updated'] = time.time()
                    continue
                job['state'] = 'running'
                job['updated'] = time.time()
            self._run(job, volumes, kind)
            del volumes, kind

    def _run(self, job, volumes, kind):
        result_extension = '.zip' if kind == 'zip' else self.FORMAT_SPECS[volumes[0]['format']][0]
        final_path = self.output_dir / (job['id'] + result_extension)
        partial_path = final_path.with_suffix(final_path.suffix + '.part')
        try:
            if job['cancel'].is_set():
                raise InterruptedError('已取消导出')
            needs_browser = any(volume['format'] == 'pdf' for volume in volumes)
            browser = self.browser_finder() if needs_browser else None
            if needs_browser and not browser:
                raise RuntimeError('未找到 Edge 或 Chrome 浏览器程序')

            used_names = set()
            with tempfile.TemporaryDirectory(prefix='vocab_job_') as directory:
                if kind != 'zip':
                    volume = volumes[0]
                    if volume['format'] == 'pdf':
                        source = Path(directory) / '0.html'
                        target = Path(directory) / '0.pdf'
                        source.write_text(volume['content'], encoding='utf-8')
                        self.renderer(browser, str(source), str(target), job['cancel'])
                        if job['cancel'].is_set():
                            raise InterruptedError('已取消导出')
                        shutil.copyfile(target, partial_path)
                    else:
                        partial_path.write_bytes(self._encode_text(
                            volume['content'], volume['format']))
                    with self.lock:
                        job['completed'] = 1
                        job['updated'] = time.time()
                else:
                    with zipfile.ZipFile(
                            partial_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                        for index, volume in enumerate(volumes):
                            if job['cancel'].is_set():
                                raise InterruptedError('已取消导出')
                            fmt = volume['format']
                            extension = self.FORMAT_SPECS[fmt][0]
                            filename = self._with_extension(volume['filename'], extension)
                            filename = self._unique_name(filename, used_names)
                            if fmt == 'pdf':
                                source = Path(directory) / f'{index}.html'
                                target = Path(directory) / f'{index}.pdf'
                                source.write_text(volume['content'], encoding='utf-8')
                                self.renderer(browser, str(source), str(target), job['cancel'])
                                archive.write(target, arcname=filename)
                            else:
                                archive.writestr(
                                    filename, self._encode_text(volume['content'], fmt))
                            if job['cancel'].is_set():
                                raise InterruptedError('已取消导出')
                            with self.lock:
                                job['completed'] = index + 1
                                job['updated'] = time.time()

            if job['cancel'].is_set():
                raise InterruptedError('已取消导出')
            os.replace(partial_path, final_path)
            with self.lock:
                if job['cancel'].is_set():
                    raise InterruptedError('已取消导出')
                job['path'] = str(final_path)
                job['size'] = final_path.stat().st_size
                job['state'] = 'done'
                job['updated'] = time.time()
        except InterruptedError:
            with self.lock:
                job['state'] = 'cancelled'
                job['path'] = None
                job['size'] = 0
                job['updated'] = time.time()
        except Exception as error:
            with self.lock:
                job['state'] = 'error'
                job['error'] = str(error)
                job['path'] = None
                job['size'] = 0
                job['updated'] = time.time()
        finally:
            for path in (partial_path, final_path if job.get('state') != 'done' else None):
                if path:
                    try:
                        Path(path).unlink(missing_ok=True)
                    except OSError:
                        pass

    def get(self, job_id):
        with self.lock:
            self._cleanup_locked()
            job = self.jobs.get(job_id)
            return dict(job) if job else None

    def status(self, job_id):
        with self.lock:
            self._cleanup_locked()
            job = self.jobs.get(job_id)
            if not job:
                return None
            status = {
                key: job[key]
                for key in ('id', 'state', 'completed', 'total', 'error', 'format')
            }
            if job['state'] == 'queued':
                waiting = [entry[0]['id'] for entry in self.pending if not entry[0]['cancel'].is_set()]
                status['queuePosition'] = waiting.index(job_id) + 1 if job_id in waiting else 0
            return status

    def file(self, job_id):
        with self.lock:
            self._cleanup_locked()
            job = self.jobs.get(job_id)
            if not job or job['state'] != 'done' or not job['path']:
                return None
            path = Path(job['path'])
            if not path.is_file():
                self._remove_job_locked(job_id)
                return None
            return {
                'path': path, 'size': path.stat().st_size,
                'mime': job['mime'], 'filename': job['filename'],
            }

    def cancel(self, job_id):
        with self.condition:
            self._cleanup_locked()
            job = self.jobs.get(job_id)
            if not job:
                return None
            original_state = job['state']
            if original_state == 'queued':
                job['cancel'].set()
                self.pending = deque(
                    entry for entry in self.pending if entry[0]['id'] != job_id)
                job['state'] = 'cancelled'
                job['updated'] = time.time()
            elif original_state == 'running':
                job['cancel'].set()
                job['updated'] = time.time()
            return original_state

    def shutdown(self, timeout=5):
        with self.condition:
            if not self.closed:
                self.closed = True
                for job in self.jobs.values():
                    if job['state'] == 'queued':
                        job['cancel'].set()
                        job['state'] = 'cancelled'
                        job['updated'] = time.time()
                    elif job['state'] == 'running':
                        job['cancel'].set()
                self.pending.clear()
                self.condition.notify_all()
            threads = list(self.threads)
        deadline = time.monotonic() + timeout
        for thread in threads:
            thread.join(max(0, deadline - time.monotonic()))
        with self.lock:
            for job_id in list(self.jobs):
                self._remove_job_locked(job_id)
        if not any(thread.is_alive() for thread in threads):
            try:
                self._temp.cleanup()
            except OSError:
                pass
