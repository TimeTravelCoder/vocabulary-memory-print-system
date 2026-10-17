"""Bounded local export jobs with progress, cancellation, and disk-backed results."""
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile


class ExportBusyError(RuntimeError):
    """Raised when both export worker slots are occupied."""


class ExportConflictError(RuntimeError):
    """Raised when a client tries to reuse an existing job id."""


class ExportJobs:
    def __init__(self, renderer, browser_finder, retention_seconds=1800, max_finished=20):
        self.renderer = renderer
        self.browser_finder = browser_finder
        self.retention_seconds = retention_seconds
        self.max_finished = max_finished
        self.jobs = {}
        self.lock = threading.RLock()
        self.capacity = threading.BoundedSemaphore(2)
        self._temp = tempfile.TemporaryDirectory(prefix='vocab_exports_')
        self.output_dir = Path(self._temp.name)
        self.threads = set()
        self.closed = False

    @staticmethod
    def safe_name(value):
        name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', str(value)).strip(' .')[:180]
        return name or 'vocabulary'

    @staticmethod
    def _with_extension(value, extension):
        name = ExportJobs.safe_name(value)
        if not name.lower().endswith(extension):
            name += extension
        return name

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
        if not isinstance(payload, dict):
            raise ValueError('请求内容必须是 JSON 对象')
        kind = payload.get('kind')
        if kind not in ('pdf', 'zip'):
            raise ValueError('不支持的任务类型')
        volumes = payload.get('volumes') if kind == 'zip' else [payload]
        if (not isinstance(volumes, list) or not volumes or len(volumes) > 1000 or
                any(not isinstance(v, dict) or not isinstance(v.get('html'), str) or
                    not v['html'].strip() for v in volumes)):
            raise ValueError('没有有效的排版内容，或分卷数量超过 1000')
        fmt = payload.get('format', 'pdf')
        if fmt not in ('pdf', 'html') or (kind == 'pdf' and fmt != 'pdf'):
            raise ValueError('不支持的导出格式')
        job_id = payload.get('id') or uuid.uuid4().hex
        if not isinstance(job_id, str) or not re.fullmatch(r'[a-f0-9]{32}', job_id):
            raise ValueError('任务编号无效')

        with self.lock:
            self._cleanup_locked()
            if self.closed:
                raise ExportBusyError('导出服务正在关闭')
            if job_id in self.jobs:
                raise ExportConflictError('任务编号重复')
        if not self.capacity.acquire(blocking=False):
            raise ExportBusyError('已有两个导出任务，请等待或取消后重试')

        extension = '.zip' if kind == 'zip' else '.pdf'
        requested_name = payload.get(
            'zipFilename' if kind == 'zip' else 'filename', 'vocabulary' + extension)
        job = {
            'id': job_id, 'state': 'queued', 'completed': 0, 'total': len(volumes),
            'error': '', 'cancel': threading.Event(), 'updated': time.time(),
            'path': None, 'size': 0,
            'filename': self._with_extension(requested_name, extension),
            'mime': 'application/zip' if kind == 'zip' else 'application/pdf',
        }
        registered = False
        try:
            with self.lock:
                if self.closed:
                    raise ExportBusyError('导出服务正在关闭')
                if job_id in self.jobs:
                    raise ExportConflictError('任务编号重复')
                self.jobs[job_id] = job
                registered = True
                thread = threading.Thread(
                    target=self._run, args=(job, volumes, fmt, kind),
                    name=f'vocab-export-{job_id[:8]}', daemon=False)
                self.threads.add(thread)
            thread.start()
        except Exception:
            with self.lock:
                if registered:
                    self.jobs.pop(job_id, None)
                if 'thread' in locals():
                    self.threads.discard(thread)
            self.capacity.release()
            raise
        return job_id

    def _run(self, job, volumes, fmt, kind):
        final_path = self.output_dir / (job['id'] + ('.zip' if kind == 'zip' else '.pdf'))
        partial_path = final_path.with_suffix(final_path.suffix + '.part')
        try:
            if job['cancel'].is_set():
                raise InterruptedError('已取消导出')
            with self.lock:
                job['state'] = 'running'
                job['updated'] = time.time()
            browser = self.browser_finder() if fmt == 'pdf' else None
            if fmt == 'pdf' and not browser:
                raise RuntimeError('未找到 Edge 或 Chrome 浏览器程序')

            used_names = set()
            with tempfile.TemporaryDirectory(prefix='vocab_job_') as directory:
                if kind == 'pdf':
                    source = Path(directory) / '0.html'
                    target = Path(directory) / '0.pdf'
                    source.write_text(volumes[0]['html'], encoding='utf-8')
                    self.renderer(browser, str(source), str(target), job['cancel'])
                    if job['cancel'].is_set():
                        raise InterruptedError('已取消导出')
                    shutil.copyfile(target, partial_path)
                    with self.lock:
                        job['completed'] = 1
                        job['updated'] = time.time()
                else:
                    with zipfile.ZipFile(partial_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                        for index, volume in enumerate(volumes):
                            if job['cancel'].is_set():
                                raise InterruptedError('已取消导出')
                            extension = '.' + fmt
                            filename = self._with_extension(
                                volume.get('filename', f'volume_{index + 1}'), extension)
                            if filename in used_names:
                                filename = f'{index + 1}_{filename}'
                            used_names.add(filename)
                            if fmt == 'pdf':
                                source = Path(directory) / f'{index}.html'
                                target = Path(directory) / f'{index}.pdf'
                                source.write_text(volume['html'], encoding='utf-8')
                                self.renderer(browser, str(source), str(target), job['cancel'])
                                archive.write(target, arcname=filename)
                            else:
                                archive.writestr(filename, volume['html'].encode('utf-8'))
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
            with self.lock:
                self.threads.discard(threading.current_thread())
            self.capacity.release()

    def get(self, job_id):
        with self.lock:
            self._cleanup_locked()
            job = self.jobs.get(job_id)
            return dict(job) if job else None

    def status(self, job_id):
        job = self.get(job_id)
        if not job:
            return None
        return {key: job[key] for key in ('id', 'state', 'completed', 'total', 'error')}

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
        with self.lock:
            self._cleanup_locked()
            job = self.jobs.get(job_id)
            if not job:
                return None
            if job['state'] in ('queued', 'running'):
                job['cancel'].set()
                job['updated'] = time.time()
            return job['state']

    def shutdown(self, timeout=5):
        with self.lock:
            self.closed = True
            for job in self.jobs.values():
                if job['state'] in ('queued', 'running'):
                    job['cancel'].set()
            threads = list(self.threads)
        deadline = time.monotonic() + timeout
        for thread in threads:
            thread.join(max(0, deadline - time.monotonic()))
        with self.lock:
            for job_id in list(self.jobs):
                self._remove_job_locked(job_id)
        try:
            self._temp.cleanup()
        except OSError:
            pass
