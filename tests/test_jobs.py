from pathlib import Path
import io
import sys
import threading
import time
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '单词打印系统'))
from export_jobs import ExportBusyError, ExportConflictError, ExportJobs


class JobTests(unittest.TestCase):
    def manager(self, renderer=None, browser_finder=lambda: None, **kwargs):
        manager = ExportJobs(renderer, browser_finder, **kwargs)
        self.addCleanup(manager.shutdown)
        return manager

    def wait_job(self, manager, job_id):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status = manager.status(job_id)
            if status['state'] in ('done', 'error', 'cancelled'):
                return status
            time.sleep(0.01)
        self.fail('job did not finish')

    def test_pdf_job_generates_disk_download_and_reports_progress(self):
        def render(browser, source, output, cancel):
            Path(output).write_bytes(b'%PDF-test')

        manager = self.manager(render, lambda: 'edge')
        job_id = manager.create({'kind': 'pdf', 'html': '<h1>Test</h1>', 'filename': 'test'})
        status = self.wait_job(manager, job_id)
        artifact = manager.file(job_id)
        self.assertEqual(status['state'], 'done')
        self.assertEqual(status['completed'], 1)
        self.assertEqual(artifact['filename'], 'test.pdf')
        self.assertEqual(artifact['path'].read_bytes(), b'%PDF-test')
        self.assertNotIn('data', manager.get(job_id))

    def test_zip_progress_and_safe_distinct_names(self):
        manager = self.manager()
        job_id = manager.create({'kind': 'zip', 'format': 'html', 'zipFilename': 'set', 'volumes': [
            {'filename': '../a.html', 'html': 'one'},
            {'filename': '../a.html', 'html': 'two'},
        ]})
        self.assertEqual(self.wait_job(manager, job_id)['completed'], 2)
        artifact = manager.file(job_id)
        self.assertEqual(artifact['filename'], 'set.zip')
        with zipfile.ZipFile(io.BytesIO(artifact['path'].read_bytes())) as archive:
            self.assertEqual(len(set(archive.namelist())), 2)
            self.assertTrue(all('/' not in name and '\\' not in name for name in archive.namelist()))

    def test_cancel_stops_work_and_removes_output(self):
        entered = threading.Event()

        def render(browser, source, output, cancel):
            entered.set()
            cancel.wait(2)
            if cancel.is_set():
                raise InterruptedError()

        manager = self.manager(render, lambda: 'edge')
        job_id = manager.create({'kind': 'pdf', 'html': 'test'})
        self.assertTrue(entered.wait(1))
        self.assertIn(manager.cancel(job_id), ('queued', 'running'))
        self.assertEqual(self.wait_job(manager, job_id)['state'], 'cancelled')
        self.assertIsNone(manager.file(job_id))

    def test_cancel_after_completion_is_idempotent_and_keeps_file(self):
        manager = self.manager()
        job_id = manager.create({'kind': 'zip', 'format': 'html', 'volumes': [
            {'filename': 'one', 'html': 'done'},
        ]})
        self.assertEqual(self.wait_job(manager, job_id)['state'], 'done')
        before = manager.file(job_id)['path'].read_bytes()
        self.assertEqual(manager.cancel(job_id), 'done')
        self.assertEqual(manager.status(job_id)['state'], 'done')
        self.assertEqual(manager.file(job_id)['path'].read_bytes(), before)

    def test_failure_reports_error(self):
        manager = self.manager()
        job_id = manager.create({'kind': 'pdf', 'html': 'test'})
        self.assertEqual(self.wait_job(manager, job_id)['state'], 'error')
        self.assertIn('未找到', manager.status(job_id)['error'])

    def test_busy_and_duplicate_jobs_have_distinct_errors(self):
        hold = threading.Event()
        entered = threading.Barrier(3)

        def render(browser, source, output, cancel):
            entered.wait(1)
            hold.wait(2)
            if cancel.is_set():
                raise InterruptedError()

        manager = self.manager(render, lambda: 'edge')
        first_id = '1' * 32
        manager.create({'id': first_id, 'kind': 'pdf', 'html': 'one'})
        manager.create({'id': '2' * 32, 'kind': 'pdf', 'html': 'two'})
        entered.wait(1)
        with self.assertRaises(ExportBusyError):
            manager.create({'kind': 'pdf', 'html': 'three'})
        hold.set()
        self.wait_job(manager, first_id)
        with self.assertRaises(ExportConflictError):
            manager.create({'id': first_id, 'kind': 'pdf', 'html': 'again'})

    def test_finished_retention_is_bounded(self):
        manager = self.manager(max_finished=2)
        ids = []
        for index in range(3):
            job_id = manager.create({'kind': 'zip', 'format': 'html', 'volumes': [
                {'filename': str(index), 'html': str(index)},
            ]})
            self.wait_job(manager, job_id)
            ids.append(job_id)
        manager.status(ids[-1])
        self.assertIsNone(manager.status(ids[0]))
        self.assertIsNotNone(manager.status(ids[1]))
        self.assertIsNotNone(manager.status(ids[2]))

    def test_bad_payload_rejected(self):
        manager = self.manager()
        bad = (
            {'kind': 'bad'},
            {'kind': 'zip', 'volumes': []},
            {'kind': 'pdf', 'html': 'test', 'id': '../../file'},
            [],
        )
        for payload in bad:
            with self.assertRaises(ValueError):
                manager.create(payload)


if __name__ == '__main__':
    unittest.main()
