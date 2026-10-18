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

    def test_data_job_writes_utf8_csv_with_safe_download_name(self):
        manager = self.manager()
        job_id = manager.create({
            'kind': 'data', 'format': 'csv', 'filename': '学习记录',
            'content': '\ufeffword,definition\nhello,你好',
        })
        status = self.wait_job(manager, job_id)
        artifact = manager.file(job_id)
        self.assertEqual(status['state'], 'done')
        self.assertEqual(status['format'], 'csv')
        self.assertEqual(artifact['filename'], '学习记录.csv')
        self.assertEqual(artifact['mime'], 'text/csv; charset=utf-8')
        data = artifact['path'].read_bytes()
        self.assertTrue(data.startswith(b'\xef\xbb\xbfword'))
        self.assertFalse(data.startswith(b'\xef\xbb\xbf\xef\xbb\xbf'))

    def test_mixed_text_zip_supports_anki_and_case_insensitive_names(self):
        manager = self.manager()
        job_id = manager.create({
            'kind': 'zip', 'format': 'csv', 'zipFilename': '../学习包',
            'volumes': [
                {'filename': 'LIST.csv', 'content': 'word,meaning\none,一'},
                {'filename': 'list.CSV', 'content': 'word,meaning\ntwo,二'},
                {'filename': 'CON', 'format': 'anki', 'content': 'three\t三'},
            ],
        })
        self.assertEqual(self.wait_job(manager, job_id)['completed'], 3)
        artifact = manager.file(job_id)
        self.assertTrue(artifact['filename'].endswith('.zip'))
        with zipfile.ZipFile(artifact['path']) as archive:
            names = archive.namelist()
            self.assertEqual(len({name.casefold() for name in names}), 3)
            self.assertTrue(all('/' not in name and '\\' not in name for name in names))
            self.assertIn('LIST.csv', names)
            self.assertIn('list (2).CSV', names)
            self.assertIn('_CON.txt', names)
            self.assertEqual(archive.read('_CON.txt').decode('utf-8'), 'three\t三')

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

        manager = self.manager(render, lambda: 'edge', max_pending=2)
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

    def test_fifo_queue_reports_position_and_queued_cancel_frees_space(self):
        entered = threading.Event()
        release = threading.Event()
        order = []

        def render(browser, source, output, cancel):
            value = Path(source).read_text(encoding='utf-8')
            order.append(value)
            if value == 'first':
                entered.set()
                release.wait(2)
            if cancel.is_set():
                raise InterruptedError()
            Path(output).write_bytes(b'%PDF-test')

        manager = self.manager(
            render, lambda: 'edge', max_workers=1, max_pending=2)
        first = manager.create({'kind': 'pdf', 'html': 'first'})
        self.assertTrue(entered.wait(1))
        second = manager.create({'kind': 'pdf', 'html': 'second'})
        self.assertEqual(manager.status(second)['queuePosition'], 1)
        with self.assertRaises(ExportBusyError):
            manager.create({'kind': 'pdf', 'html': 'full'})
        self.assertEqual(manager.cancel(second), 'queued')
        self.assertEqual(manager.status(second)['state'], 'cancelled')
        third = manager.create({'kind': 'pdf', 'html': 'third'})
        release.set()
        self.assertEqual(self.wait_job(manager, first)['state'], 'done')
        self.assertEqual(self.wait_job(manager, third)['state'], 'done')
        self.assertEqual(order, ['first', 'third'])

    def test_queue_rejects_excessive_combined_input_size(self):
        hold = threading.Event()
        entered = threading.Event()

        def render(browser, source, output, cancel):
            entered.set()
            hold.wait(2)
            if cancel.is_set():
                raise InterruptedError()
            Path(output).write_bytes(b'%PDF-test')

        manager = self.manager(
            render, lambda: 'edge', max_workers=1, max_pending=3,
            max_queued_bytes=12)
        first = manager.create({'kind': 'pdf', 'html': '12345678'})
        self.assertTrue(entered.wait(1))
        with self.assertRaises(ExportBusyError):
            manager.create({'kind': 'pdf', 'html': 'abcdefgh'})
        hold.set()
        self.assertEqual(self.wait_job(manager, first)['state'], 'done')

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
            {'kind': 'data', 'format': 'pdf', 'content': 'bad'},
            {'kind': 'data-zip', 'format': 'pdf', 'volumes': [
                {'content': 'bad'},
            ]},
            {'kind': 'pdf', 'html': 'test', 'id': '../../file'},
            [],
        )
        for payload in bad:
            with self.assertRaises(ValueError):
                manager.create(payload)


if __name__ == '__main__':
    unittest.main()
