import io
import json
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from runner import Service, LIMIT


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.s = Service({'state_dir': str(self.root/'state'), 'projects': {'test': str(self.root)},
                          'default_project': 'test', 'default_backend': 'codex', 'codex_bin': 'codex', 'retry_seconds': 1})
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
            self.assertEqual(db.execute("SELECT value FROM meta WHERE key='offset'").fetchone()[0], '3')

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

    def test_backend_selection_and_status(self):
        first = self.update()
        first['message']['text'] = '/claude'
        self.s.ingest([first, self.update(2)])
        third = self.update(3)
        third['message']['text'] = '/codex hello'
        status = self.update(4)
        status['message']['text'] = '/status'
        self.s.ingest([third, status, status])
        with self.s.db() as db:
            self.assertEqual([tuple(r) for r in db.execute('SELECT id,backend,instruction FROM jobs ORDER BY id')],
                             [(2,'claude','test'),(3,'codex','hello')])
            self.assertEqual(db.execute('SELECT count(*) FROM outbox').fetchone()[0], 4)

    def test_repository_then_agent_selection_queues_job(self):
        self.s.cfg['repository_selection'] = True
        self.s.github_owner = lambda: 'owner'
        class Result:
            returncode = 0
            stdout = 'owner/one\nowner/two\n'
        with patch('runner.subprocess.run', return_value=Result()):
            self.s.ingest([self.update()])
        with self.s.db() as db:
            markup = json.loads(db.execute('SELECT markup FROM outbox').fetchone()[0])
            self.assertEqual(markup['inline_keyboard'][0][0]['text'], 'owner/one')
            choice = markup['inline_keyboard'][0][0]['callback_data']
        callback = {'update_id': 2, 'callback_query': {'id': 'callback-1', 'data': choice,
                    'message': {'chat': {'id': 123}}}}
        with patch.object(self.s, 'api', return_value=True): self.s.ingest([callback])
        with self.s.db() as db:
            agent = json.loads(db.execute('SELECT markup FROM outbox ORDER BY id DESC').fetchone()[0])
            data = agent['inline_keyboard'][0][0]['callback_data']
        callback['update_id'] = 3
        callback['callback_query']['id'] = 'callback-2'
        callback['callback_query']['data'] = data
        with patch.object(self.s, 'api', return_value=True): self.s.ingest([callback])
        with self.s.db() as db:
            job = db.execute('SELECT project,backend FROM jobs').fetchone()
            self.assertEqual(tuple(job), ('github:owner/one', 'claude'))

    def test_new_repository_button_accepts_callback(self):
        self.s.cfg['repository_selection'] = True
        self.s.github_owner = lambda: 'owner'
        class Result:
            returncode = 0
            stdout = ''
        with patch('runner.subprocess.run', return_value=Result()):
            self.s.ingest([self.update()])
        with self.s.db() as db:
            markup = json.loads(db.execute('SELECT markup FROM outbox').fetchone()[0])
            choice = markup['inline_keyboard'][-1][0]['callback_data']
        self.assertEqual(choice, 'n:1:new')
        callback = {'update_id': 2, 'callback_query': {'id': 'callback-new', 'data': choice,
                    'message': {'chat': {'id': 123}}}}
        with patch.object(self.s, 'api', return_value=True):
            self.s.ingest([callback])
        with self.s.db() as db:
            self.assertEqual(db.execute('SELECT state FROM requests WHERE id=1').fetchone()[0], 'new-name')

    def test_auto_repository_selection_queues_workspace(self):
        self.s.cfg.update({'repository_selection': True, 'auto_repository_selection': True,
                           'default_project': 'workspace', 'projects': {'workspace': str(self.root)}})
        self.s.ingest([self.update()])
        self.assertEqual(self.row()['project'], 'workspace')

    def test_claude_result(self):
        update = self.update()
        update['message']['text'] = '/claude answer'
        self.s.ingest([update])
        root = self.root
        class Child:
            stdin = io.StringIO()
            stdout = iter([json.dumps({'type':'result','subtype':'success','is_error':False,'result':'Claude reply'})])
            def wait(self):
                (root/'RESUME_NOTE.md').unlink()
                return 0
        with patch('runner.subprocess.Popen', return_value=Child()) as launch:
            self.s.work_once()
            self.assertIn('--append-system-prompt', launch.call_args.args[0])
            self.assertIn('--effort', launch.call_args.args[0])
            self.assertEqual(launch.call_args.args[0][launch.call_args.args[0].index('--effort') + 1], 'xhigh')
        self.assertEqual(self.row()['summary'], 'Claude reply')
        self.assertEqual(self.row()['status'], 'done')

    def test_claude_limit_preserves_note(self):
        update = self.update()
        update['message']['text'] = '/claude work'
        self.s.ingest([update])
        class Child:
            stdin = io.StringIO()
            stdout = iter([json.dumps({'type':'result','subtype':'error_during_execution',
                                      'is_error':True,'result':"You've hit your limit"})])
            def wait(self): return 1
        with patch('runner.subprocess.Popen', return_value=Child()):
            self.s.work_once()
        self.assertEqual(self.row()['status'], 'retry')
        self.assertTrue((self.root/'RESUME_NOTE.md').exists())

    def test_codex_uses_xhigh_reasoning(self):
        self.s.ingest([self.update()])
        root = self.root
        class Child:
            stdin = io.StringIO()
            stdout = iter([json.dumps({'type':'turn.completed'})])
            def wait(self):
                (root/'RESUME_NOTE.md').unlink()
                return 0
        with patch('runner.subprocess.Popen', return_value=Child()) as launch:
            self.s.work_once()
        self.assertIn('model_reasoning_effort="xhigh"', launch.call_args.args[0])

    def test_other_project_job_runs_while_one_project_is_still_busy(self):
        other = self.root / 'other'
        other.mkdir()
        self.s.cfg['projects']['other'] = str(other)
        self.s.ingest([self.update(1)])
        second = self.update(2)
        second['message']['text'] = '/project other\nhello'
        self.s.ingest([second])

        slow_started = threading.Event()
        release_slow = threading.Event()
        root = self.root.resolve()
        other_resolved = other.resolve()

        class SlowChild:
            stdin = io.StringIO()
            def __init__(self):
                def gen():
                    slow_started.set()
                    release_slow.wait(5)
                    yield json.dumps({'type': 'turn.completed'})
                self.stdout = gen()
            def wait(self):
                (root / 'RESUME_NOTE.md').unlink()
                return 0

        class FastChild:
            stdin = io.StringIO()
            stdout = iter([json.dumps({'type': 'turn.completed'})])
            def wait(self):
                (other_resolved / 'RESUME_NOTE.md').unlink()
                return 0

        def popen(cmd, **kwargs):
            return SlowChild() if Path(kwargs['cwd']) == root else FastChild()

        with patch('runner.subprocess.Popen', side_effect=popen):
            slow_worker = threading.Thread(target=self.s.work_once)
            slow_worker.start()
            self.assertTrue(slow_started.wait(2), 'first job never started')
            # A second, unrelated project must be claimable and finish while the
            # first job is still mid-flight, instead of waiting for it to finish.
            self.assertTrue(self.s.work_once())
            with self.s.db() as db:
                self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=2').fetchone()[0], 'done')
                self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=1').fetchone()[0], 'running')
            release_slow.set()
            slow_worker.join(5)
        with self.s.db() as db:
            self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=1').fetchone()[0], 'done')

    def test_queue_lists_active_jobs(self):
        self.s.ingest([self.update(1)])
        queue_update = self.update(2)
        queue_update['message']['text'] = '/queue'
        self.s.ingest([queue_update])
        with self.s.db() as db:
            text = db.execute('SELECT text FROM outbox ORDER BY id DESC LIMIT 1').fetchone()['text']
        self.assertIn('1 [codex] test - queued', text)

    def test_cancel_queued_job_removes_it(self):
        self.s.ingest([self.update(1)])
        cancel = self.update(2)
        cancel['message']['text'] = '/cancel 1'
        self.s.ingest([cancel])
        self.assertEqual(self.row()['status'], 'cancelled')
        self.assertEqual(self.row()['notified'], 1)
        self.assertFalse(self.s.work_once())

    def test_cancel_unknown_job(self):
        cancel = self.update(1)
        cancel['message']['text'] = '/cancel 999'
        self.s.ingest([cancel])
        with self.s.db() as db:
            text = db.execute('SELECT text FROM outbox ORDER BY id DESC LIMIT 1').fetchone()['text']
        self.assertIn('찾지 못했습니다', text)

    def test_cancel_finished_job_is_rejected(self):
        update = self.update()
        update['message']['text'] = '/claude answer'
        self.s.ingest([update])
        root = self.root
        class Child:
            stdin = io.StringIO()
            stdout = iter([json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'ok'})])
            def wait(self):
                (root / 'RESUME_NOTE.md').unlink()
                return 0
        with patch('runner.subprocess.Popen', return_value=Child()):
            self.s.work_once()
        cancel = self.update(2)
        cancel['message']['text'] = '/cancel 1'
        self.s.ingest([cancel])
        with self.s.db() as db:
            text = db.execute('SELECT text FROM outbox ORDER BY id DESC LIMIT 1').fetchone()['text']
        self.assertIn('이미 done 상태', text)

    def test_cancel_running_job_sends_sigterm_and_marks_cancelled(self):
        self.s.ingest([self.update(1)])
        started = threading.Event()
        release = threading.Event()
        root = self.root.resolve()

        class SlowChild:
            stdin = io.StringIO()
            pid = 424242
            def __init__(self):
                def gen():
                    started.set()
                    release.wait(5)
                    yield json.dumps({'type': 'turn.completed'})
                self.stdout = gen()
            def wait(self):
                (root / 'RESUME_NOTE.md').unlink()
                return 0

        with patch('runner.subprocess.Popen', return_value=SlowChild()):
            worker = threading.Thread(target=self.s.work_once)
            worker.start()
            self.assertTrue(started.wait(2), 'job never started')
            cancel = self.update(2)
            cancel['message']['text'] = '/cancel 1'
            with patch('runner.os.killpg') as killpg:
                self.s.ingest([cancel])
                killpg.assert_called_once_with(424242, signal.SIGTERM)
            with self.s.db() as db:
                text = db.execute('SELECT text FROM outbox ORDER BY id DESC LIMIT 1').fetchone()['text']
            self.assertIn('중지를 요청했습니다', text)
            release.set()
            worker.join(5)
        self.assertEqual(self.row()['status'], 'cancelled')

    def test_heartbeat_sends_progress_message_during_long_job(self):
        self.s.cfg['heartbeat_seconds'] = 0.05
        self.s.ingest([self.update()])
        root = self.root
        release = threading.Event()

        class Child:
            stdin = io.StringIO()
            def __init__(self):
                def gen():
                    release.wait(2)
                    yield json.dumps({'type': 'turn.completed'})
                self.stdout = gen()
            def wait(self):
                (root / 'RESUME_NOTE.md').unlink()
                return 0

        with patch('runner.subprocess.Popen', return_value=Child()):
            worker = threading.Thread(target=self.s.work_once)
            worker.start()
            time.sleep(0.3)
            release.set()
            worker.join(5)
        with self.s.db() as db:
            texts = [r['text'] for r in db.execute('SELECT text FROM outbox').fetchall()]
        self.assertTrue(any('아직 실행 중' in t for t in texts), texts)

    def test_job_timeout_marks_retry_with_note(self):
        self.s.cfg['job_timeout_seconds'] = 0.05
        self.s.ingest([self.update(1)])
        release = threading.Event()

        class SlowChild:
            stdin = io.StringIO()
            pid = 555555
            def __init__(self):
                def gen():
                    release.wait(5)
                    yield json.dumps({'type': 'turn.completed'})
                self.stdout = gen()
            def wait(self):
                return 0

        with patch('runner.subprocess.Popen', return_value=SlowChild()), patch('runner.os.killpg') as killpg:
            worker = threading.Thread(target=self.s.work_once)
            worker.start()
            deadline = time.time() + 3
            while not killpg.called and time.time() < deadline:
                time.sleep(0.01)
            self.assertTrue(killpg.called, 'watchdog never fired')
            release.set()
            worker.join(5)
        self.assertEqual(self.row()['status'], 'retry')
        with self.s.db() as db:
            text = db.execute('SELECT text FROM outbox ORDER BY id DESC LIMIT 1').fetchone()['text']
        self.assertIn('시간 초과', text)

    def test_diff_job_reports_commit_stat(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        subprocess.run(['git', '-C', str(self.root), 'config', 'user.email', 'a@b.c'], check=True)
        subprocess.run(['git', '-C', str(self.root), 'config', 'user.name', 'x'], check=True)
        (self.root / 'seed.txt').write_text('seed')
        subprocess.run(['git', '-C', str(self.root), 'add', 'seed.txt'], check=True)
        subprocess.run(['git', '-C', str(self.root), 'commit', '-q', '-m', 'seed'], check=True)

        self.s.ingest([self.update()])
        root = self.root

        class Child:
            stdin = io.StringIO()
            def __init__(self):
                (root / 'new.txt').write_text('hi')
                subprocess.run(['git', '-C', str(root), 'add', 'new.txt'], check=True)
                subprocess.run(['git', '-C', str(root), 'commit', '-q', '-m', 'agent change'], check=True)
                self.stdout = iter([json.dumps({'type': 'turn.completed'})])
            def wait(self):
                (root / 'RESUME_NOTE.md').unlink()
                return 0

        # run_job's own git_head() calls real `git` via subprocess.run too, which internally
        # calls Popen -- let those through to the real subprocess.Popen and only fake the
        # actual agent-CLI launch, otherwise git_head's own subprocess.run would get the Child
        # mock back instead of a real process.
        real_popen = subprocess.Popen
        def popen_side_effect(cmd, **kwargs):
            return real_popen(cmd, **kwargs) if cmd[0] == 'git' else Child()

        with patch('runner.subprocess.Popen', side_effect=popen_side_effect):
            self.s.work_once()
        self.assertEqual(self.row()['status'], 'done')

        diff_update = self.update(2)
        diff_update['message']['text'] = '/diff 1'
        self.s.ingest([diff_update])
        with self.s.db() as db:
            text = db.execute('SELECT text FROM outbox ORDER BY id DESC LIMIT 1').fetchone()['text']
        self.assertIn('new.txt', text)
        self.assertIn('agent change', text)

    def test_diff_job_without_commits_reports_no_info(self):
        diff_update = self.update(1)
        diff_update['message']['text'] = '/diff 999'
        self.s.ingest([diff_update])
        with self.s.db() as db:
            text = db.execute('SELECT text FROM outbox ORDER BY id DESC LIMIT 1').fetchone()['text']
        self.assertIn('찾지 못했습니다', text)

    def test_reply_to_completion_message_inherits_project_and_backend(self):
        update = self.update()
        update['message']['text'] = '/claude first'
        self.s.ingest([update])
        with self.s.db() as db:
            db.execute('INSERT INTO job_messages(message_id, job_id) VALUES(?,?)', (999, 1))
        reply_update = self.update(2)
        reply_update['message']['text'] = 'second, continue'
        reply_update['message']['reply_to_message'] = {'message_id': 999}
        self.s.ingest([reply_update])
        with self.s.db() as db:
            job2 = db.execute('SELECT project, backend, instruction FROM jobs WHERE id=2').fetchone()
        self.assertEqual(job2['project'], 'test')
        self.assertEqual(job2['backend'], 'claude')
        self.assertEqual(job2['instruction'], 'second, continue')

    def test_reply_to_github_project_job_bypasses_repo_buttons(self):
        with self.s.db() as db:
            db.execute("INSERT INTO jobs(id,chat,project,instruction,backend,status) VALUES(1,'123','github:owner/repo','first','codex','done')")
            db.execute('INSERT INTO job_messages(message_id, job_id) VALUES(555,1)')
        self.s.cfg['repository_selection'] = True
        reply_update = self.update(2)
        reply_update['message']['text'] = 'keep going'
        reply_update['message']['reply_to_message'] = {'message_id': 555}
        self.s.ingest([reply_update])
        with self.s.db() as db:
            job2 = db.execute('SELECT project, backend FROM jobs WHERE id=2').fetchone()
        self.assertEqual(job2['project'], 'github:owner/repo')
        self.assertEqual(job2['backend'], 'codex')

    def test_usage_summary_counts_limit_hits(self):
        self.s.ingest([self.update()])
        class Child:
            stdin = io.StringIO()
            stdout = iter([json.dumps({'type': 'turn.failed', 'error': {'message': 'usage_limit_exceeded'}})])
            def wait(self): return 1
        with patch('runner.subprocess.Popen', return_value=Child()):
            self.s.work_once()
        usage_update = self.update(2)
        usage_update['message']['text'] = '/usage'
        self.s.ingest([usage_update])
        with self.s.db() as db:
            text = db.execute('SELECT text FROM outbox ORDER BY id DESC LIMIT 1').fetchone()['text']
        self.assertIn('한도 도달 1회', text)

    def test_idea_capture_and_list_and_clear(self):
        idea1 = self.update(1)
        idea1['message']['text'] = '/idea 다크모드 추가하면 좋겠다'
        idea2 = self.update(2)
        idea2['message']['text'] = '/idea 알림 소리 옵션'
        self.s.ingest([idea1, idea2])
        with self.s.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM ideas').fetchone()[0], 2)
            confirm_text = db.execute('SELECT text FROM outbox ORDER BY id DESC LIMIT 1').fetchone()['text']
        self.assertIn('대기 2개', confirm_text)

        list_update = self.update(3)
        list_update['message']['text'] = '/ideas'
        self.s.ingest([list_update])
        with self.s.db() as db:
            listing = db.execute('SELECT text FROM outbox ORDER BY id DESC LIMIT 1').fetchone()['text']
        self.assertIn('다크모드', listing)
        self.assertIn('알림 소리', listing)

        clear_update = self.update(4)
        clear_update['message']['text'] = '/ideas 비우기'
        self.s.ingest([clear_update])
        with self.s.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM ideas').fetchone()[0], 0)

        empty_update = self.update(5)
        empty_update['message']['text'] = '/ideas'
        self.s.ingest([empty_update])
        with self.s.db() as db:
            empty_text = db.execute('SELECT text FROM outbox ORDER BY id DESC LIMIT 1').fetchone()['text']
        self.assertIn('없습니다', empty_text)

    def test_digest_lists_finished_and_active_then_advances_watermark(self):
        self.s.ingest([self.update(1)])
        root = self.root
        class Child:
            stdin = io.StringIO()
            stdout = iter([json.dumps({'type': 'turn.completed'})])
            def wait(self):
                (root / 'RESUME_NOTE.md').unlink()
                return 0
        with patch('runner.subprocess.Popen', return_value=Child()):
            self.s.work_once()
        self.s.ingest([self.update(2)])  # stays queued behind nothing, but project is free -> queued

        digest_update = self.update(3)
        digest_update['message']['text'] = '/digest'
        self.s.ingest([digest_update])
        with self.s.db() as db:
            first_digest = db.execute('SELECT text FROM outbox ORDER BY id DESC LIMIT 1').fetchone()['text']
        self.assertIn('끝난 작업 1건', first_digest)
        self.assertIn('대기/실행/차단 중 1건', first_digest)

        digest_update2 = self.update(4)
        digest_update2['message']['text'] = '/digest'
        self.s.ingest([digest_update2])
        with self.s.db() as db:
            second_digest = db.execute('SELECT text FROM outbox ORDER BY id DESC LIMIT 1').fetchone()['text']
        self.assertIn('새로 끝난 작업 없음', second_digest)

    def test_action_required_blocks_and_retry_command_requeues(self):
        self.s.ingest([self.update()])
        class Child:
            stdin = io.StringIO()
            stdout = iter([json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'ACTION_REQUIRED: GitHub 권한 필요'}}),
                           json.dumps({'type':'turn.completed'})])
            def wait(self): return 0
        with patch('runner.subprocess.Popen', return_value=Child()):
            self.s.work_once()
        self.assertEqual(self.row()['status'], 'blocked')
        retry = self.update(2)
        retry['message']['text'] = '/retry 1'
        self.s.ingest([retry])
        self.assertEqual(self.row()['status'], 'retry')


if __name__ == '__main__': unittest.main()
