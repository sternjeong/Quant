#!/usr/bin/env python3
"""Durable Telegram polling and single-worker Codex supervisor (stdlib only)."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import threading
import time
import urllib.request

HERE = Path(__file__).resolve().parent
LIMIT = re.compile(r"usage_limit_(?:reached|exceeded)|usage limit|rate_limit_exceeded|rate limit|too many requests|\b429\b", re.I)


def env_file(path):
    result = {}
    if path and Path(path).exists():
        for line in Path(path).read_text().splitlines():
            key, sep, value = line.strip().removeprefix('export ').partition('=')
            if sep and not key.startswith('#'):
                result[key.strip()] = value.strip().strip('\"\'')
    return result


class Service:
    def __init__(self, cfg):
        self.cfg = cfg
        self.state = Path(cfg['state_dir'])
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.secrets = env_file(cfg.get('env_file'))
        self.secrets.update({k: v for k, v in os.environ.items() if k.startswith('TELEGRAM_')})
        self.token = self.secrets.get('TELEGRAM_BOT_TOKEN', '')
        self.chat = str(self.secrets.get('TELEGRAM_CHAT_ID', ''))
        self.stop = threading.Event()
        self.child = None
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, chat TEXT, project TEXT,
              instruction TEXT, status TEXT DEFAULT 'queued', attempts INTEGER DEFAULT 0,
              due REAL DEFAULT 0, summary TEXT DEFAULT '', notified INTEGER DEFAULT 0);
            ''')

    def db(self):
        db = sqlite3.connect(self.state / 'queue.sqlite', timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def api(self, method, data):
        req = urllib.request.Request('https://api.telegram.org/bot' + self.token + '/' + method,
                                     data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=40) as response:
            body = json.load(response)
        if not body.get('ok'):
            raise RuntimeError('Telegram request rejected')
        return body['result']

    def ingest(self, updates):
        with self.db() as db:
            for update in updates:
                uid = int(update['update_id'])
                msg = update.get('message', {})
                chat = msg.get('chat', {})
                instruction = msg.get('text', '')
                if str(chat.get('id')) == self.chat and chat.get('type') == 'private' and instruction:
                    project = self.cfg['default_project']
                    if instruction.startswith('/project '):
                        first, _, instruction = instruction.partition('\n')
                        project = first.split(maxsplit=1)[1].strip()
                    if project in self.cfg['projects'] and instruction.strip():
                        db.execute('INSERT OR IGNORE INTO jobs(id,chat,project,instruction) VALUES(?,?,?,?)',
                                   (uid, self.chat, project, instruction))
                db.execute("INSERT INTO meta VALUES('offset',?) ON CONFLICT(key) DO UPDATE SET value=max(cast(value as integer),cast(excluded.value as integer))", (str(uid + 1),))

    def poll(self):
        while not self.stop.is_set():
            try:
                with self.db() as db:
                    row = db.execute("SELECT value FROM meta WHERE key='offset'").fetchone()
                self.ingest(self.api('getUpdates', {'offset': int(row[0]) if row else 0,
                                                   'timeout': 25, 'allowed_updates': ['message']}))
            except Exception:
                print('Telegram polling unavailable; retry in 30 seconds', flush=True)
                self.stop.wait(30)

    def redact(self, text):
        for value in self.secrets.values():
            if len(value) >= 6:
                text = text.replace(value, '[REDACTED]')
        return re.sub(r'(?i)(?:sk-[\w-]+|\d{6,}:[\w-]{20,})', '[REDACTED]', text)

    def run_job(self, job):
        project = Path(self.cfg['projects'][job['project']]).resolve()
        note = project / 'RESUME_NOTE.md'
        if job['attempts'] and not note.exists():
            self.finish(job['id'], 'done', 'RESUME_NOTE.md 삭제 확인: 재시도 종료')
            return
        if not job['attempts'] and note.exists():
            self.finish(job['id'], 'blocked', '기존 RESUME_NOTE.md가 있어 새 작업 실행 보류')
            return
        if not note.exists():
            note.write_text(f'# Resume job {job["id"]}\n작업을 시작합니다. 원래 지시는 영속 큐에 보관되어 있습니다.\n'
                            'README, PROGRESS, git status/log로 진행 상태를 확인하고 원래 지시를 완료하세요.\n')
        with self.db() as db:
            db.execute("UPDATE jobs SET status='running', attempts=attempts+1 WHERE id=?", (job['id'],))
        prompt = (f'프로젝트: {project}\n이 프로젝트에서만 작업하세요. RESUME_NOTE.md를 먼저 읽고 이어서 작업하세요. '
                  '중요 단계마다 메모를 갱신하세요. commit과 push 성공 후에만 메모를 삭제하세요. '
                  'RESUME_NOTE.md는 커밋 대상에서 제외하세요. '
                  '최종 응답은 래퍼가 텔레그램으로 전달하므로 완료 요약을 최종 응답으로 작성하세요.\n\n'
                  '원래 텔레그램 지시:\n' + job['instruction'])
        cmd = [self.cfg['codex_bin'], '-a', 'never', 'exec', '--ephemeral', '--json', '--color', 'never',
               '-s', self.cfg.get('sandbox', 'danger-full-access'), '-C', str(project),
               '-c', 'sandbox_workspace_write.network_access=true',
               '-c', 'developer_instructions=' + json.dumps((HERE / 'worker_prompt.md').read_text(), ensure_ascii=False), '-']
        child_env = os.environ.copy()
        if self.cfg.get('codex_home'):
            child_env['CODEX_HOME'] = self.cfg['codex_home']
        for key in self.secrets:
            if key.startswith('TELEGRAM_'):
                child_env.pop(key, None)
        limited, failed, completed, summary = False, False, False, ''
        try:
            self.child = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT, text=True, cwd=project, env=child_env,
                                          start_new_session=True)
            self.child.stdin.write(prompt)
            self.child.stdin.close()
            for line in self.child.stdout:
                # Raw model/tool output is deliberately never persisted or sent to journald.
                try:
                    event = json.loads(line)
                except ValueError:
                    limited |= bool(LIMIT.search(line))
                    continue
                kind = event.get('type', '')
                if kind in ('error', 'turn.failed'):
                    limited |= bool(LIMIT.search(json.dumps(event)))
                    failed |= kind == 'turn.failed'
                completed |= kind == 'turn.completed'
                item = event.get('item', {})
                if kind == 'item.completed' and item.get('type') == 'agent_message':
                    summary = self.redact(item.get('text', ''))[:3000]
            rc = self.child.wait()
        except (OSError, BrokenPipeError):
            if self.child:
                self.child.wait()
            rc = 1
        finally:
            self.child = None
        if rc == 0 and completed and not failed and not limited and not note.exists():
            self.finish(job['id'], 'done', summary or '작업 완료')
        elif limited or self.stop.is_set() or (rc == 0 and completed and note.exists()):
            delay = min(self.cfg.get('retry_max_seconds', 3600),
                        self.cfg.get('retry_seconds', 900) * 2 ** min(job['attempts'], 8))
            with self.db() as db:
                db.execute("UPDATE jobs SET status='retry', due=? WHERE id=?", (time.time() + delay, job['id']))
        else:
            self.finish(job['id'], 'blocked', f'실행 오류(exit={rc}). 인증/CLI/권한 점검 필요; 메모 유지')

    def finish(self, uid, status, summary):
        with self.db() as db:
            db.execute('UPDATE jobs SET status=?,summary=? WHERE id=?', (status, summary, uid))

    def work_once(self):
        with self.db() as db:
            job = db.execute("""SELECT * FROM jobs j WHERE status IN ('queued','retry') AND due<=?
              AND NOT EXISTS (SELECT 1 FROM jobs k WHERE k.project=j.project AND k.id<j.id
              AND k.status IN ('queued','retry','running','blocked')) ORDER BY id LIMIT 1""", (time.time(),)).fetchone()
        if job:
            self.run_job(job)
        return bool(job)

    def notify(self):
        with self.db() as db:
            rows = db.execute("SELECT * FROM jobs WHERE status IN ('done','blocked') AND notified=0").fetchall()
        for row in rows:
            try:
                self.api('sendMessage', {'chat_id': row['chat'], 'text': f"작업 {row['id']} [{row['status']}]\n{row['summary']}"})
                with self.db() as db:
                    db.execute('UPDATE jobs SET notified=1 WHERE id=?', (row['id'],))
            except Exception:
                break

    def run(self):
        if not self.token or not self.chat:
            raise SystemExit('Configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID; see README.md')
        lock = (self.state / 'service.lock').open('w')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with self.db() as db:
            db.execute("UPDATE jobs SET status='retry' WHERE status='running'")
        def shutdown(*_):
            self.stop.set()
            if self.child:
                try:
                    os.killpg(self.child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        thread = threading.Thread(target=self.poll, daemon=True)
        thread.start()
        while not self.stop.is_set():
            self.work_once()
            self.notify()
            self.stop.wait(2)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    Service(json.loads(Path(args.config).read_text())).run()


if __name__ == '__main__':
    main()
