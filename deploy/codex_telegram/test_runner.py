import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from runner import Service, LIMIT


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.s = Service({'state_dir': str(self.root/'state'), 'projects': {'test': str(self.root)},
                          'default_project': 'test', 'codex_bin': 'codex', 'retry_seconds': 1})
        self.s.chat = '123'

    def update(self, uid=1, chat=123):
        return {'update_id': uid, 'message': {'chat': {'id': chat, 'type': 'private'}, 'text': 'test'}}

    def row(self):
        with self.s.db() as db:
            return db.execute('SELECT * FROM jobs WHERE id=1').fetchone()

    def test_auth_duplicate_offset(self):
        self.s.ingest([self.update(), self.update(), self.update(2, 999)])
        with self.s.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT value FROM meta').fetchone()[0], '3')

    def test_limit_then_resume(self):
        self.s.ingest([self.update()])
        class Child:
            stdin = io.StringIO()
            stdout = iter([json.dumps({'type':'turn.failed','error':{'message':"You've hit your usage limit."}})])
            def wait(self): return 1
        with patch('runner.subprocess.Popen', return_value=Child()):
            self.s.work_once()
        self.assertEqual(self.row()['status'], 'retry')
        self.assertTrue((self.root/'RESUME_NOTE.md').exists())
        # A new message is durably received while another job is waiting.
        self.s.ingest([self.update(3)])
        self.assertFalse(self.s.work_once())
        (self.root/'RESUME_NOTE.md').unlink()
        with self.s.db() as db:
            db.execute('UPDATE jobs SET due=0 WHERE id=1')
        self.s.work_once()
        self.assertEqual(self.row()['status'], 'done')

    def test_nonlimit_failure_is_blocked(self):
        self.s.ingest([self.update()])
        with patch('runner.subprocess.Popen', side_effect=OSError()): self.s.work_once()
        self.assertEqual(self.row()['status'], 'blocked')

    def test_actual_retry_invokes_worker_and_finishes(self):
        self.s.ingest([self.update()])
        class Child:
            stdin = io.StringIO()
            stdout = iter([json.dumps({'type':'turn.failed','error':{'message':'usage_limit_exceeded'}})])
            def wait(self): return 1
        with patch('runner.subprocess.Popen', return_value=Child()):
            self.s.work_once()
        with self.s.db() as db:
            db.execute('UPDATE jobs SET due=0')
        root = self.root
        class Resumed:
            stdin = io.StringIO()
            stdout = iter([json.dumps({'type':'turn.completed'})])
            def wait(self):
                (root/'RESUME_NOTE.md').unlink()
                return 0
        child = Resumed()
        with patch('runner.subprocess.Popen', return_value=child) as launch:
            self.s.work_once()
            launch.assert_called_once()
        self.assertEqual(self.row()['status'], 'done')
        self.assertEqual(self.row()['attempts'], 2)

    def test_error_patterns(self):
        for text in ('usage_limit_exceeded', 'rate_limit_exceeded', "You've hit your usage limit."):
            self.assertIsNotNone(LIMIT.search(text))
        self.assertIsNone(LIMIT.search('401 Unauthorized'))


if __name__ == '__main__': unittest.main()
