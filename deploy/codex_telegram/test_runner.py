import io
import json
from pathlib import Path
import signal
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import runner
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

    def test_news_command_reads_latest_saved_digest(self):
        data_dir = self.root / 'data'
        data_dir.mkdir()
        with sqlite3.connect(data_dir / 'quant.db') as db:
            db.execute('CREATE TABLE news_ticker_digests(id INTEGER PRIMARY KEY, ticker TEXT, article_count INTEGER, summary TEXT, created_at TEXT)')
            db.execute("INSERT INTO news_ticker_digests(ticker, article_count, summary, created_at) VALUES('XLK', 2, '새 요약', '2026-01-01')")
        update = self.update()
        update['message']['text'] = '/news XLK'
        self.s.ingest([update])
        with self.s.db() as db:
            reply = db.execute('SELECT text FROM outbox').fetchone()[0]
        self.assertIn('XLK (2건): 새 요약', reply)

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

        # This test is about claim/concurrency correctness, not the resource-headroom gate
        # (which has its own dedicated tests) -- pin capacity available so it isn't flaky
        # depending on the real host's load/memory at test time.
        with patch('runner.subprocess.Popen', side_effect=popen), patch.object(self.s, 'has_capacity', return_value=True):
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

    def test_has_capacity_always_true_when_nothing_running(self):
        # Even under real system load, the very first job must never be blocked -- otherwise a
        # chronically "full" reading (from something unrelated on the box) would stall the whole
        # pipeline forever with nobody watching.
        with patch('runner.os.getloadavg', return_value=(999.0, 999.0, 999.0)), \
             patch.object(self.s, 'available_memory_mb', return_value=0):
            self.assertTrue(self.s.has_capacity())

    def test_has_capacity_blocks_second_job_under_high_load(self):
        with self.s.children_lock:
            self.s.children[1] = object()
        with patch('runner.os.getloadavg', return_value=(999.0, 999.0, 999.0)), \
             patch('runner.os.cpu_count', return_value=2):
            self.assertFalse(self.s.has_capacity())

    def test_has_capacity_blocks_second_job_under_low_memory(self):
        with self.s.children_lock:
            self.s.children[1] = object()
        with patch('runner.os.getloadavg', return_value=(0.1, 0.1, 0.1)), \
             patch.object(self.s, 'available_memory_mb', return_value=100):
            self.assertFalse(self.s.has_capacity())

    def test_has_capacity_allows_second_job_when_headroom_exists(self):
        with self.s.children_lock:
            self.s.children[1] = object()
        with patch('runner.os.getloadavg', return_value=(0.1, 0.1, 0.1)), \
             patch('runner.os.cpu_count', return_value=4), \
             patch.object(self.s, 'available_memory_mb', return_value=4096):
            self.assertTrue(self.s.has_capacity())

    def test_claim_job_returns_none_without_capacity(self):
        self.s.ingest([self.update()])
        with patch.object(self.s, 'has_capacity', return_value=False):
            self.assertIsNone(self.s.claim_job())
        with self.s.db() as db:
            self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=1').fetchone()[0], 'queued')

    def test_queue_lists_active_jobs(self):
        self.s.ingest([self.update(1)])
        queue_update = self.update(2)
        queue_update['message']['text'] = '/queue'
        self.s.ingest([queue_update])
        with self.s.db() as db:
            text = db.execute('SELECT text FROM outbox ORDER BY id DESC LIMIT 1').fetchone()['text']
        self.assertIn('1 [codex] test - queued', text)

    def test_experiment_command_is_removed(self):
        # 2주 실험 슈퍼바이저는 2026-09-25 삭제됐다(docs/prune/PRUNE_E.md) — /experiment 는 알 수 없는 명령이고
        # 작업을 큐에 넣거나 .experiment-control 을 쓰지 않는다.
        update = self.update(1)
        update['message']['text'] = '/experiment codex Day 1의 데이터 감사를 해줘'
        help_update = self.update(2)
        help_update['message']['text'] = '/help'
        self.s.ingest([update, help_update])
        with self.s.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0], 0)
            replies = [r['text'] for r in db.execute('SELECT text FROM outbox ORDER BY id')]
        self.assertIn('알 수 없는 명령', replies[0])
        self.assertNotIn('/experiment', replies[1])
        self.assertFalse((self.root / '.experiment-control').exists())
        self.assertFalse(hasattr(self.s, 'experiment_status'))

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

    def test_hypothesis_promote_button_runs_admin_and_clears_buttons(self):
        callback = {'update_id': 3, 'callback_query': {'id': 'cb-h', 'data': 'h:promote:H-20261005-001',
                    'message': {'chat': {'id': 123}, 'message_id': 77}}}
        calls = []
        with patch.object(self.s, 'run_hypothesis_admin', return_value=(True, 'ok')) as admin, \
                patch.object(self.s, 'api', side_effect=lambda m, d: calls.append((m, d)) or True):
            self.s.ingest([callback])
        admin.assert_called_once_with('promote', 'H-20261005-001')
        self.assertIn('editMessageReplyMarkup', [m for m, _ in calls])
        with self.s.db() as db:
            text = db.execute('SELECT text FROM outbox ORDER BY id DESC LIMIT 1').fetchone()['text']
        self.assertIn('paper 편입 승인', text)

    def test_models_command_and_cycle_button_write_shared_file(self):
        update = self.update()
        update['message']['text'] = '/models'
        self.s.ingest([update])
        with self.s.db() as db:
            reply = db.execute('SELECT text,markup FROM outbox ORDER BY id DESC LIMIT 1').fetchone()
        self.assertIn('Writer 가설 작성: opus (기본)', reply['text'])
        data = json.loads(reply['markup'])['inline_keyboard'][1][0]['callback_data']  # writer
        self.assertEqual(data, 'm:1')
        with patch.object(self.s, 'api', return_value=True):
            self.s.ingest([{'update_id': 9, 'callback_query': {'id': 'm', 'data': data, 'message': {'chat': {'id': 123}}}}])
        saved = json.loads(self.s.agent_models_path().read_text())
        self.assertEqual(saved['writer']['model'], 'haiku')        # opus → haiku (순환)
        self.assertEqual(self.s.agent_model('writer', 'opus'), 'haiku')

    def test_hypothesis_button_rejects_bad_id_and_foreign_chat(self):
        with patch.object(self.s, 'run_hypothesis_admin') as admin, patch.object(self.s, 'api', return_value=True):
            self.s.ingest([{'update_id': 4, 'callback_query': {'id': 'x', 'data': 'h:promote:; rm -rf /',
                                                               'message': {'chat': {'id': 123}}}}])
            self.s.ingest([{'update_id': 5, 'callback_query': {'id': 'y', 'data': 'h:promote:H-20261005-001',
                                                               'message': {'chat': {'id': 999}}}}])
            self.s.ingest([{'update_id': 6, 'callback_query': {'id': 'z', 'data': 'h:delete:H-20261005-001',
                                                               'message': {'chat': {'id': 123}}}}])
        admin.assert_not_called()

    # ---- /processes: 목록은 core/process_registry.py 에서 ast 로 읽는다(하드코딩 목록 없음) ----------------

    def outbox(self):
        with self.s.db() as db:
            return [(r['text'], json.loads(r['markup']) if r['markup'] else None)
                    for r in db.execute('SELECT text,markup FROM outbox ORDER BY id')]

    def send(self, text, uid=1):
        update = self.update(uid)
        update['message']['text'] = text
        self.s.ingest([update])

    def tap(self, data, uid=50):
        callback = {'update_id': uid, 'callback_query': {'id': 'cb-1', 'data': data, 'message': {'chat': {'id': 123}}}}
        with patch.object(self.s, 'api', return_value=True) as api:
            self.s.ingest([callback])
        return api

    def registry(self):
        return runner.load_process_catalog()

    def test_processes_command_lists_every_registry_job_grouped_by_category(self):
        self.send('/processes')
        messages = self.outbox()
        text = '\n'.join(t for t, _ in messages)
        buttons = [b for _, m in messages if m for row in m['inline_keyboard'] for b in row]
        catalog = self.registry()
        self.assertGreaterEqual(len(catalog), 27)
        self.assertEqual([b['callback_data'] for b in buttons if b['callback_data'].startswith('p:')],
                         [f'p:{e["key"]}' for c in ('alert', 'research', 'maintenance')
                          for e in catalog if e['category'] == c])
        for entry in catalog:
            self.assertIn(entry['key'], text)
            self.assertIn(entry['label'], text)
        self.assertIn(f'자동 잡 {len(catalog)}개', messages[0][0])
        self.assertIn('✅ 챔피언 전략 신호 변경 알림', text)
        self.assertIn('⏸ 챔피언 paper 자동 주문', text)  # 레지스트리 기본값(꺼짐)을 따른다
        for title in ('🔔 알림', '🔬 연구·기록', '🧰 유지보수'):
            self.assertIn(title, text)
        self.assertNotIn('2주 전략 검증 실험', text)
        self.assertNotIn('/experiment', text)
        self.assertNotIn('야간 전략 미세튜닝', text)  # 2026-09-24 삭제
        self.assertTrue(all(len(t) <= runner.TELEGRAM_TEXT_LIMIT for t, _ in messages))
        with self.s.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0], 0)

    def test_processes_button_toggles_by_key_and_keeps_toggle_file_format(self):
        self.tap('p:champion_signal_alert')
        self.assertFalse(self.s.is_process_enabled('champion_signal_alert', True))
        state = json.loads((self.root / 'data' / 'process_toggles.json').read_text())
        self.assertEqual(set(state['champion_signal_alert']), {'enabled', 'updated_at', 'actor'})
        self.assertIs(state['champion_signal_alert']['enabled'], False)
        text, markup = self.outbox()[-1]
        self.assertIn('⏸ 끔: 챔피언 전략 신호 변경 알림', text)
        self.assertIn('🔔 알림', text)
        self.assertIn({'text': '켜기 · 챔피언 전략 신호 변경 알림', 'callback_data': 'p:champion_signal_alert'},
                      [b for row in markup['inline_keyboard'] for b in row])
        self.tap('p:champion_signal_alert', uid=51)
        self.assertTrue(self.s.is_process_enabled('champion_signal_alert', True))

    def test_processes_can_toggle_jobs_missing_from_the_old_hardcoded_list(self):
        for uid, key in enumerate(('candidate_ledger_record', 'account_snapshot_sync', 'guru_holdings_sync',
                                   'alpaca_verification_bootstrap'), start=50):
            self.tap(f'p:{key}', uid=uid)
            self.assertFalse(self.s.is_process_enabled(key, True), key)

    def test_processes_text_on_off_commands(self):
        self.send('/processes off guru_holdings_sync', uid=1)
        self.assertFalse(self.s.is_process_enabled('guru_holdings_sync', True))
        self.assertIn('⏸ 끔: 거장 포트폴리오 자동 동기화 (guru_holdings_sync)', self.outbox()[-1][0])
        self.send('/processes on guru_holdings_sync', uid=2)
        self.assertTrue(self.s.is_process_enabled('guru_holdings_sync', False))
        self.send('/processes on no_such_job', uid=3)
        self.assertIn('알 수 없는 잡: no_such_job', self.outbox()[-1][0])
        self.send('/processes flip guru_holdings_sync', uid=4)
        self.assertIn('사용법', self.outbox()[-1][0])
        with self.s.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0], 0)

    def test_paper_auto_trade_needs_confirmation_to_turn_on_by_text(self):
        self.assertFalse(self.s.is_process_enabled('paper_auto_trade', False))
        self.send('/processes on paper_auto_trade', uid=1)
        self.assertFalse(self.s.is_process_enabled('paper_auto_trade', False))
        self.assertFalse((self.root / 'data' / 'process_toggles.json').exists())  # 아무것도 쓰지 않음
        text, markup = self.outbox()[-1]
        self.assertIn('정말 켜시겠습니까', text)
        self.assertIn('/processes on paper_auto_trade confirm', text)
        self.assertEqual(markup['inline_keyboard'][0][0]['callback_data'], 'pc:paper_auto_trade')
        self.send('/processes on paper_auto_trade confirm', uid=2)
        self.assertTrue(self.s.is_process_enabled('paper_auto_trade', False))
        self.assertIn('✅ 켬: 챔피언 paper 자동 주문', self.outbox()[-1][0])
        # 끄기는 확인 없이 즉시
        self.send('/processes off paper_auto_trade', uid=3)
        self.assertFalse(self.s.is_process_enabled('paper_auto_trade', True))

    def test_paper_auto_trade_button_asks_then_confirm_button_enables(self):
        self.tap('p:paper_auto_trade', uid=50)
        self.assertFalse(self.s.is_process_enabled('paper_auto_trade', False))
        text, markup = self.outbox()[-1]
        self.assertIn('정말 켜시겠습니까', text)
        self.tap(markup['inline_keyboard'][0][0]['callback_data'], uid=51)
        self.assertTrue(self.s.is_process_enabled('paper_auto_trade', False))
        self.tap('p:paper_auto_trade', uid=52)  # 켜진 상태에서 누르면 즉시 끔
        self.assertFalse(self.s.is_process_enabled('paper_auto_trade', True))
        self.assertIn('⏸ 끔: 챔피언 paper 자동 주문', self.outbox()[-1][0])

    def test_processes_toggle_ignores_unknown_or_old_index_buttons(self):
        for index, data in enumerate(('p:9999', 'p:0', 'pc:not_a_job')):
            api = self.tap(data, uid=60 + index)
            self.assertIn('목록이 바뀌었습니다', api.call_args[0][1]['text'])
        self.assertEqual(self.outbox(), [])
        self.assertFalse((self.root / 'data' / 'process_toggles.json').exists())

    def test_processes_list_is_split_under_the_telegram_limit(self):
        with patch.object(runner, 'TELEGRAM_TEXT_LIMIT', 120):
            self.send('/processes')
        messages = self.outbox()
        self.assertTrue(all(len(t) <= 120 for t, _ in messages))
        text = '\n'.join(t for t, _ in messages)
        buttons = [b['callback_data'] for _, m in messages if m for row in m['inline_keyboard'] for b in row]
        self.assertEqual(sorted(buttons), sorted(f'p:{e["key"]}' for e in self.registry()))
        for entry in self.registry():
            self.assertIn(entry['key'], text)
        self.assertGreater(len(messages), 4)  # 머리말 + 카테고리 3개보다 많이 나뉨

    def test_split_text_keeps_line_boundaries_and_hard_splits_long_lines(self):
        self.assertEqual(runner.split_text('a\nb\nc', limit=3), ['a\nb', 'c'])
        self.assertEqual(runner.split_text('abcdefg', limit=3), ['abc', 'def', 'g'])
        self.assertEqual(runner.split_text('', limit=3), [''])

    def test_help_shows_actual_job_count(self):
        self.send('/help')
        text = self.outbox()[-1][0]
        self.assertIn(f'/processes: 자동 잡 {len(self.registry())}개', text)
        self.assertNotIn('16개', text)

    def test_unreadable_registry_reports_instead_of_crashing(self):
        broken = self.root / 'broken_registry.py'
        broken.write_text('PROCESS_REGISTRY = build()\n')
        self.s.cfg['process_registry_path'] = str(broken)
        self.send('/processes')
        self.assertIn('잡 목록(core/process_registry.py)을 읽지 못했습니다', self.outbox()[-1][0])
        self.send('/help', uid=2)
        self.assertIn('(개수 확인 불가)', self.outbox()[-1][0])


if __name__ == '__main__': unittest.main()


class RepoReadCommandTests(unittest.TestCase):
    """/cat /log /repo — LLM 없이 폰에서 저장소를 읽는 명령 (docs/TELEGRAM_REPO_BRIDGE_SPEC.md 3-2)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'repo'
        self.root.mkdir()
        self.s = Service({'state_dir': str(Path(self.tmp.name) / 'state'),
                          'projects': {'quant': str(self.root)}, 'default_project': 'quant',
                          'default_backend': 'codex', 'codex_bin': 'codex', 'retry_seconds': 1})

    def git(self, *args):
        subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=t', '-c', 'user.email=t@e.com',
                        '-c', 'commit.gpgsign=false', *args], check=True, capture_output=True)

    def make_repo(self):
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(self.root)], check=True, capture_output=True)
        (self.root / 'PROGRESS.md').write_text('# progress\n')
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'first commit')

    # ---- /cat ----

    def test_cat_shows_the_tail_and_reports_total_length(self):
        (self.root / 'PROGRESS.md').write_text('\n'.join(f'line {i}' for i in range(1, 101)) + '\n')
        reply = self.s.cat_file('PROGRESS.md 5')
        self.assertIn('전체 100줄 중 마지막 5줄', reply)
        self.assertIn('line 100', reply)
        self.assertNotIn('line 95', reply)  # 5줄만

    def test_cat_caps_the_line_count_and_defaults_sensibly(self):
        (self.root / 'big.md').write_text('\n'.join(f'l{i}' for i in range(500)) + '\n')
        capped = self.s.cat_file(f'big.md 9999')
        self.assertIn(f'마지막 {Service.CAT_MAX_LINES}줄', capped)
        self.assertIn(f'마지막 {Service.CAT_MAX_LINES}줄', self.s.cat_file('big.md'))  # 인자 없으면 기본 상한

    def test_cat_refuses_to_escape_the_repository(self):
        secret = Path(self.tmp.name) / 'outside.txt'
        secret.write_text('TOP SECRET')
        for attempt in ('../outside.txt', '/etc/passwd', '../../etc/passwd'):
            reply = self.s.cat_file(attempt)
            self.assertNotIn('TOP SECRET', reply, attempt)
            self.assertNotIn('root:', reply, attempt)

    def test_cat_refuses_binary_and_missing_files(self):
        (self.root / 'x.bin').write_bytes(b'\x00\x01\x02' * 100)
        self.assertIn('바이너리', self.s.cat_file('x.bin'))
        self.assertIn('그런 파일이 없습니다', self.s.cat_file('nope.md'))
        self.assertIn('사용법', self.s.cat_file(''))

    def test_cat_truncates_very_long_output(self):
        (self.root / 'long.md').write_text(('x' * 200 + '\n') * 60)
        reply = self.s.cat_file('long.md 60')
        self.assertLess(len(reply), Service.CAT_MAX_CHARS + 200)

    def test_cat_redacts_secret_looking_content(self):
        (self.root / 'oops.md').write_text('token: sk-abcdefghijklmnopqrstuvwxyz012345\n')
        self.assertNotIn('sk-abcdefghijklmnopqrstuvwxyz012345', self.s.cat_file('oops.md'))

    # ---- /log, /repo ----

    def test_log_lists_recent_commits(self):
        self.make_repo()
        reply = self.s.repo_log('5')
        self.assertIn('first commit', reply)

    def test_log_count_is_bounded(self):
        self.make_repo()
        self.assertIn(f'최근 커밋 {Service.LOG_MAX_COMMITS}개', self.s.repo_log('9999'))

    def test_repo_state_reports_head_and_uncommitted_files(self):
        self.make_repo()
        clean = self.s.repo_state()
        self.assertIn('first commit', clean)
        self.assertIn('미커밋 수정: 없음', clean)

        (self.root / 'PROGRESS.md').write_text('# progress\n\nVM 에이전트가 덧붙인 줄\n')
        dirty = self.s.repo_state()
        self.assertIn('미커밋 수정 1개', dirty)
        self.assertIn('PROGRESS.md', dirty)

    def test_read_commands_never_crash_outside_a_git_repo(self):
        for reply in (self.s.repo_log('3'), self.s.repo_state()):
            self.assertIsInstance(reply, str)
            self.assertTrue(reply)


class MindlessCommitTests(unittest.TestCase):
    """/note(비공개 경로) 와 /progress(공개 저장소 즉시 커밋) — docs/TELEGRAM_REPO_BRIDGE_SPEC.md 3-1."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'repo'
        self.root.mkdir()
        self.s = Service({'state_dir': str(self.base / 'state'),
                          'projects': {'quant': str(self.root)}, 'default_project': 'quant',
                          'default_backend': 'codex', 'codex_bin': 'codex', 'retry_seconds': 1})
        self.s.chat = '123'
        self.s.token = 'test-token'

    # ---- /note ----

    def test_note_is_written_under_a_dated_path(self):
        reply, path = self.s.save_note('기억해둘 아이디어', time.strptime('2026-09-24 15:30', '%Y-%m-%d %H:%M'))
        self.assertIn('메모 저장', reply)
        self.assertEqual(path, self.root / 'notes' / '2026-09' / '24.md')
        self.assertIn('기억해둘 아이디어', path.read_text())
        self.assertIn('## 15:30', path.read_text())

    def test_notes_append_rather_than_overwrite(self):
        when = time.strptime('2026-09-24 10:00', '%Y-%m-%d %H:%M')
        self.s.save_note('첫 번째', when)
        _, path = self.s.save_note('두 번째', when)
        body = path.read_text()
        self.assertIn('첫 번째', body)
        self.assertIn('두 번째', body)

    def test_note_refuses_secrets_without_echoing_them(self):
        leak = 'ghp_' + 'a' * 36
        reply, path = self.s.save_note(f'토큰은 {leak} 이야')
        self.assertIsNone(path)
        self.assertNotIn(leak, reply)
        self.assertFalse((self.root / 'notes').exists())

    def test_note_rejects_empty_and_overlong_input(self):
        self.assertIn('사용법', self.s.save_note('')[0])
        self.assertIn('너무 깁니다', self.s.save_note('가' * (Service.NOTE_MAX_CHARS + 1))[0])

    def test_notes_path_is_gitignored_in_the_public_repo(self):
        """공개 저장소에 메모가 새어 나가면 안 된다 — .gitignore가 실제로 막는지 git에게 물어본다."""
        repo_root = Path(__file__).resolve().parent.parent.parent
        result = subprocess.run(['git', '-C', str(repo_root), 'check-ignore', 'notes/2026-09/24.md'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, 'notes/ 가 .gitignore에 없다')

    # ---- 첨부 ----

    def test_photo_message_without_text_is_saved_instead_of_dropped(self):
        calls = {}

        def fake_api(method, data):
            calls['method'] = method
            return {'file_path': 'photos/file_1.jpg', 'file_size': 1234}

        self.s.api = fake_api
        with patch('runner.urllib.request.urlopen') as opener:
            opener.return_value.__enter__.return_value.read.return_value = b'\xff\xd8jpegbytes'
            reply = self.s.store_message_media({'photo': [{'file_id': 'small', 'file_size': 100},
                                                          {'file_id': 'big', 'file_size': 9000}],
                                                'caption': '이 화면 기억해두기'})
        self.assertEqual(calls['method'], 'getFile')
        self.assertIn('첨부 저장', reply)
        saved = list((self.root / 'notes' / 'attachments').glob('*.jpg'))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_bytes(), b'\xff\xd8jpegbytes')
        # 캡션은 그날 메모에도 남는다
        note = next((self.root / 'notes').rglob('*.md'))
        self.assertIn('이 화면 기억해두기', note.read_text())

    def test_oversized_attachment_is_refused(self):
        self.s.api = lambda method, data: {'file_path': 'x/huge.bin', 'file_size': Service.ATTACHMENT_MAX_BYTES + 1}
        reply, path = self.s.save_attachment('id', 'huge.bin')
        self.assertIn('너무 큽니다', reply)
        self.assertIsNone(path)

    def test_attachment_api_failure_is_reported_not_crashed(self):
        def boom(method, data):
            raise RuntimeError('telegram down')
        self.s.api = boom
        reply, path = self.s.save_attachment('id', 'x.jpg')
        self.assertIn('가져오지 못했습니다', reply)
        self.assertIsNone(path)

    # ---- /progress ----

    def git(self, *args, cwd=None):
        subprocess.run(['git', '-C', str(cwd or self.root), '-c', 'user.name=t', '-c', 'user.email=t@e.com',
                        '-c', 'commit.gpgsign=false', *args], check=True, capture_output=True)

    def make_repo_with_origin(self):
        origin = self.base / 'origin.git'
        subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(origin)], check=True, capture_output=True)
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(self.root)], check=True, capture_output=True)
        (self.root / 'PROGRESS.md').write_text('# PROGRESS\n\n### 작업 1\n첫 항목\n')
        (self.root / 'code.py').write_text('print(1)\n')
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'init')
        self.git('remote', 'add', 'origin', str(origin))
        self.git('push', '-q', 'origin', 'main')
        return origin

    def origin_progress(self, origin):
        return subprocess.run(['git', '-C', str(origin), 'show', 'main:PROGRESS.md'],
                              text=True, capture_output=True).stdout

    def test_progress_commits_and_pushes_to_origin(self):
        origin = self.make_repo_with_origin()
        reply = self.s.append_progress('텔레그램에서 남긴 기록')
        self.assertIn('커밋했습니다', reply)
        self.assertIn('텔레그램에서 남긴 기록', self.origin_progress(origin))
        self.assertIn('첫 항목', self.origin_progress(origin))  # 기존 내용 보존

    def test_progress_never_touches_the_dirty_working_tree(self):
        """VM 워킹트리에는 리서치 에이전트의 미커밋 수정이 늘 있다 — 절대 건드리면 안 된다."""
        origin = self.make_repo_with_origin()
        (self.root / 'PROGRESS.md').write_text('# PROGRESS\n\n### 작업 1\n첫 항목\n\nVM 에이전트가 쓰던 미커밋 줄\n')
        (self.root / 'code.py').write_text('print(2)  # 편집 중\n')
        before_progress = (self.root / 'PROGRESS.md').read_text()
        before_code = (self.root / 'code.py').read_text()
        before_status = subprocess.run(['git', '-C', str(self.root), 'status', '--porcelain'],
                                       text=True, capture_output=True).stdout

        self.assertIn('커밋했습니다', self.s.append_progress('메모 추가'))

        self.assertEqual((self.root / 'PROGRESS.md').read_text(), before_progress)  # 그대로
        self.assertEqual((self.root / 'code.py').read_text(), before_code)
        after_status = subprocess.run(['git', '-C', str(self.root), 'status', '--porcelain'],
                                      text=True, capture_output=True).stdout
        self.assertEqual(after_status, before_status)
        self.assertIn('메모 추가', self.origin_progress(origin))  # 그래도 origin에는 올라갔다

    def test_progress_refuses_secrets_because_the_repo_is_public(self):
        origin = self.make_repo_with_origin()
        leak = 'sk-ant-' + 'b' * 30
        reply = self.s.append_progress(f'키는 {leak}')
        self.assertIn('공개', reply)
        self.assertNotIn(leak, reply)
        self.assertNotIn(leak, self.origin_progress(origin))

    def test_progress_reports_failure_instead_of_pretending(self):
        self.make_repo_with_origin()
        self.git('remote', 'set-url', 'origin', str(self.base / 'gone.git'))
        reply = self.s.append_progress('어디에도 못 올라갈 메모')
        self.assertIn('커밋하지 못했습니다', reply)

    def test_progress_rejects_empty_input(self):
        self.assertIn('사용법', self.s.append_progress('   '))
