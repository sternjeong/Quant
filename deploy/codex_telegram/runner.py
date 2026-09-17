#!/usr/bin/env python3
"""Durable Telegram polling and concurrent Codex/Claude job supervisor (stdlib only)."""
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
CLAUDE_LIMIT = re.compile(r"usage limit|rate.?limit|hit your limit|out of extra usage|\b429\b", re.I)


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
        self.claim_lock = threading.Lock()
        self.children_lock = threading.Lock()
        self.children = {}
        self.cancel_lock = threading.Lock()
        self.cancel_requested = set()
        self.timeout_lock = threading.Lock()
        self.timeout_hit = set()
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, chat TEXT, project TEXT,
              instruction TEXT, status TEXT DEFAULT 'queued', attempts INTEGER DEFAULT 0,
              due REAL DEFAULT 0, summary TEXT DEFAULT '', notified INTEGER DEFAULT 0);
            ''')
            columns = {row[1] for row in db.execute('PRAGMA table_info(jobs)')}
            if 'backend' not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN backend TEXT NOT NULL DEFAULT 'codex'")
            if 'commit_before' not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN commit_before TEXT")
            if 'commit_after' not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN commit_after TEXT")
            if 'limit_hits' not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN limit_hits INTEGER NOT NULL DEFAULT 0")
            if 'created_at' not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN created_at REAL NOT NULL DEFAULT 0")
            db.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('backend',?)", (cfg.get('default_backend', 'claude'),))
            db.execute('CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY, chat TEXT, text TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY, chat TEXT, instruction TEXT, repo TEXT, state TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS repo_choices(request_id INTEGER, number INTEGER, repo TEXT, PRIMARY KEY(request_id, number))')
            db.execute('CREATE TABLE IF NOT EXISTS job_messages(message_id INTEGER PRIMARY KEY, job_id INTEGER)')
            outbox_columns = {row[1] for row in db.execute('PRAGMA table_info(outbox)')}
            if 'markup' not in outbox_columns:
                db.execute('ALTER TABLE outbox ADD COLUMN markup TEXT')
            if 'job_id' not in outbox_columns:
                db.execute('ALTER TABLE outbox ADD COLUMN job_id INTEGER')

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
                offset = db.execute("SELECT value FROM meta WHERE key='offset'").fetchone()
                if offset and uid < int(offset[0]):
                    continue
                callback = update.get('callback_query')
                if callback:
                    self.handle_callback(db, callback)
                    db.execute("INSERT INTO meta VALUES('offset',?) ON CONFLICT(key) DO UPDATE SET value=max(cast(value as integer),cast(excluded.value as integer))", (str(uid + 1),))
                    continue
                msg = update.get('message', {})
                chat = msg.get('chat', {})
                instruction = msg.get('text', '')
                if str(chat.get('id')) == self.chat and chat.get('type') == 'private' and instruction:
                    selected = db.execute("SELECT value FROM meta WHERE key='backend'").fetchone()
                    backend = selected[0] if selected else 'codex'
                    # Accept a newline after the command as well as a space.
                    parts = instruction.split(maxsplit=1)
                    command = parts[0].split('@')[0]
                    rest = parts[1] if len(parts) > 1 else ''
                    reply = None
                    if command in ('/codex', '/claude'):
                        backend = command[1:]
                        instruction = rest
                        if not rest:
                            db.execute("INSERT INTO meta VALUES('backend',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (backend,))
                            reply = f'기본 실행 대상: {backend}. 다음 메시지부터 적용됩니다.'
                    elif command == '/status':
                        rows = db.execute("SELECT id,backend,status FROM jobs ORDER BY id DESC LIMIT 8").fetchall()
                        reply = f'기본 실행 대상: {backend}\n' + '\n'.join(f'{r[0]} {r[1]} {r[2]}' for r in rows)
                    elif command == '/queue':
                        rows = db.execute("SELECT id,project,backend,status FROM jobs WHERE status IN "
                                          "('queued','retry','running','blocked') ORDER BY id").fetchall()
                        reply = ('대기/실행 중인 작업이 없습니다.' if not rows else
                                 '\n'.join(f'{r["id"]} [{r["backend"]}] {r["project"]} - {r["status"]}' for r in rows))
                    elif command == '/cancel' and rest.isdigit():
                        reply = self.cancel_job(db, int(rest))
                    elif command == '/diff' and rest.isdigit():
                        reply = self.diff_job(db, int(rest))
                    elif command == '/usage':
                        reply = self.usage_summary(db)
                    elif command == '/retry' and rest.isdigit():
                        changed = db.execute("UPDATE jobs SET status='retry',due=0,notified=0 WHERE id=? AND status='blocked'", (int(rest),)).rowcount
                        reply = f'작업 {rest} 재시도 예약됨' if changed else f'재시도할 blocked 작업 {rest}을 찾지 못했습니다.'
                    elif command in ('/start', '/help'):
                        reply = ('일반 지시: 저장소 → Claude/Codex 버튼을 차례로 선택\n'
                                 '새 저장소: 저장소 목록의 `＋ 새 private 저장소 만들기` 선택 후 이름 전송\n'
                                 '/claude 또는 /codex: 기본 실행 대상 변경\n'
                                 '/claude 지시 또는 /codex 지시: 해당 작업만 지정\n'
                                 '/status: 최근 작업 상태 8개\n/queue: 대기·실행·차단 중인 작업 전체\n'
                                 '/cancel 작업ID: 대기 중인 작업 취소 또는 실행 중인 작업 중지 요청\n'
                                 '/diff 작업ID: 그 작업이 실제로 커밋한 내용 요약\n'
                                 '/usage: 최근 7일 사용량·한도 도달 횟수\n'
                                 '/retry 작업ID: blocked 작업 재개\n'
                                 '/project quant 다음 줄에 지시: 현재 Quant를 바로 선택\n'
                                 '완료/접수 메시지에 답장(reply)하면 같은 프로젝트로 이어서 지시할 수 있습니다.')
                    elif command.startswith('/') and command != '/project':
                        reply = '알 수 없는 명령입니다. /help를 확인하세요.'
                    project = self.cfg['default_project']
                    via_reply = False
                    reply_to_id = msg.get('reply_to_message', {}).get('message_id')
                    if reply_to_id and reply is None:
                        # A plain-text reply to a job's own "접수"/완료 Telegram message continues
                        # that job's project (and backend, unless this message overrides it with
                        # /codex or /claude) — so a phone-only follow-up doesn't need to repeat
                        # /project or re-pick a repo button.
                        linked = db.execute('SELECT job_id FROM job_messages WHERE message_id=?', (reply_to_id,)).fetchone()
                        origin = db.execute('SELECT project, backend FROM jobs WHERE id=?', (linked['job_id'],)).fetchone() if linked else None
                        if origin:
                            project = origin['project']
                            via_reply = True
                            if command not in ('/codex', '/claude'):
                                backend = origin['backend']
                    reply_job_id = None
                    if instruction.startswith('/project '):
                        first, _, instruction = instruction.partition('\n')
                        project = first.split(maxsplit=1)[1].strip()
                        via_reply = False
                    if reply is None:
                        auto_repo = self.cfg.get('auto_repository_selection', False)
                        # A reply-inherited project is already unambiguous (it came from a real
                        # prior job, possibly a github:owner/repo chosen via the button flow), so
                        # it bypasses the repository-selection-button gate like /project does.
                        project_known = project in self.cfg['projects'] or (via_reply and project.startswith('github:'))
                        if project_known and instruction.strip() and (auto_repo or instruction.startswith('/project ') or via_reply or not self.cfg.get('repository_selection', False)):
                            db.execute('INSERT OR IGNORE INTO jobs(id,chat,project,instruction,backend,created_at) VALUES(?,?,?,?,?,?)',
                                       (uid, self.chat, project, instruction, backend, time.time()))
                            reply = f'접수 {uid} [{backend}] 프로젝트: {project}'
                            reply_job_id = uid
                        elif instruction.strip():
                            pending = db.execute("SELECT * FROM requests WHERE chat=? AND state='new-name' ORDER BY id DESC LIMIT 1", (self.chat,)).fetchone()
                            if pending:
                                name = instruction.strip()
                                if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', name):
                                    reply = '저장소 이름은 영문, 숫자, `.`, `_`, `-`만 사용할 수 있습니다.'
                                else:
                                    try:
                                        owner = self.github_owner()
                                    except RuntimeError:
                                        reply = 'GitHub 저장소 생성에 실패했습니다. `gh auth status`를 확인하세요.'
                                    else:
                                        repo = f'{owner}/{name}'
                                        created = subprocess.run([self.cfg.get('gh_bin', '/usr/bin/gh'), 'repo', 'create', repo, '--private'], text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                        if created.returncode:
                                            reply = 'GitHub 저장소 생성에 실패했습니다. 이름 중복이나 권한을 확인하세요.'
                                        else:
                                            db.execute("UPDATE requests SET repo=?,state='agent' WHERE id=?", (repo, pending['id']))
                                            self.queue_agent_buttons(db, pending['id'], f'새 private 저장소 `{repo}`를 만들었습니다.')
                            else:
                                db.execute('INSERT OR REPLACE INTO requests(id,chat,instruction,state) VALUES(?,?,?,?)', (uid, self.chat, instruction, 'repo'))
                                self.queue_repo_buttons(db, uid)
                                reply = None
                        else:
                            reply = '프로젝트 또는 지시를 확인하세요. /help'
                    if reply is not None:
                        self.queue_outbox(db, self.chat, reply, job_id=reply_job_id)
                db.execute("INSERT INTO meta VALUES('offset',?) ON CONFLICT(key) DO UPDATE SET value=max(cast(value as integer),cast(excluded.value as integer))", (str(uid + 1),))

    def queue_outbox(self, db, chat, text, markup=None, job_id=None):
        # Telegram's sendMessage caps a message at 4096 chars; truncate defensively so one
        # oversized reply (e.g. a big /diff) can never wedge every message queued behind it.
        db.execute('INSERT INTO outbox(chat,text,markup,job_id) VALUES(?,?,?,?)', (chat, text[:3900], json.dumps(markup) if markup else None, job_id))

    def github_owner(self):
        if self.cfg.get('github_owner'):
            return self.cfg['github_owner']
        result = subprocess.run([self.cfg.get('gh_bin', '/usr/bin/gh'), 'api', 'user', '--jq', '.login'], text=True, capture_output=True)
        if result.returncode or not result.stdout.strip():
            raise RuntimeError('GitHub CLI authentication is required')
        return result.stdout.strip()

    def queue_repo_buttons(self, db, request_id):
        try:
            owner = self.github_owner()
            result = subprocess.run([self.cfg.get('gh_bin', '/usr/bin/gh'), 'repo', 'list', owner, '--limit', '30', '--json', 'nameWithOwner', '--jq', '.[].nameWithOwner'], text=True, capture_output=True)
            if result.returncode:
                raise RuntimeError()
            repos = [x for x in result.stdout.splitlines() if x]
        except RuntimeError:
            self.queue_outbox(db, self.chat, 'GitHub 목록을 읽지 못했습니다. `gh auth status`를 확인하세요.')
            return
        for number, repo in enumerate(repos, 1):
            db.execute('INSERT OR REPLACE INTO repo_choices VALUES(?,?,?)', (request_id, number, repo))
        rows = [[{'text': repo, 'callback_data': f'r:{request_id}:{number}'}] for number, repo in enumerate(repos, 1)]
        rows.append([{'text': '＋ 새 private 저장소 만들기', 'callback_data': f'n:{request_id}:new'}])
        self.queue_outbox(db, self.chat, '이 지시를 실행할 저장소를 선택하세요.', {'inline_keyboard': rows})

    def queue_agent_buttons(self, db, request_id, text='저장소를 선택했습니다.'):
        self.queue_outbox(db, self.chat, text + '\n작업자를 선택하세요.', {'inline_keyboard': [[
            {'text': 'Claude', 'callback_data': f'a:{request_id}:claude'},
            {'text': 'Codex', 'callback_data': f'a:{request_id}:codex'}
        ]]})

    def handle_callback(self, db, callback):
        chat = str(callback.get('message', {}).get('chat', {}).get('id', ''))
        if chat != self.chat:
            return
        data = callback.get('data', '')
        try:
            kind, request_id, value = data.split(':', 2)
            request_id = int(request_id)
        except ValueError:
            return
        request = db.execute('SELECT * FROM requests WHERE id=? AND chat=?', (request_id, chat)).fetchone()
        if not request:
            return
        if kind == 'r' and request['state'] == 'repo':
            choice = db.execute('SELECT repo FROM repo_choices WHERE request_id=? AND number=?', (request_id, int(value))).fetchone()
            if choice:
                db.execute("UPDATE requests SET repo=?,state='agent' WHERE id=?", (choice['repo'], request_id))
                self.queue_agent_buttons(db, request_id, f'저장소 `{choice["repo"]}`를 선택했습니다.')
        elif kind == 'n' and request['state'] == 'repo':
            db.execute("UPDATE requests SET state='new-name' WHERE id=?", (request_id,))
            self.queue_outbox(db, chat, '새 private GitHub 저장소 이름을 다음 메시지로 보내세요.')
        elif kind == 'a' and request['state'] == 'agent' and value in ('claude', 'codex'):
            db.execute('INSERT OR IGNORE INTO jobs(id,chat,project,instruction,backend,created_at) VALUES(?,?,?,?,?,?)',
                       (request_id, chat, 'github:' + request['repo'], request['instruction'], value, time.time()))
            db.execute("UPDATE requests SET state='queued' WHERE id=?", (request_id,))
            self.queue_outbox(db, chat, f'접수 {request_id} [{value}] {request["repo"]}', job_id=request_id)
        try:
            self.api('answerCallbackQuery', {'callback_query_id': callback['id']})
        except Exception:
            pass

    def cancel_job(self, db, job_id):
        row = db.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not row:
            return f'작업 {job_id}를 찾지 못했습니다.'
        status = row['status']
        if status in ('queued', 'retry'):
            # notified=1: this reply already tells the user; run_job's async notify() would
            # otherwise send a redundant second message for a job that never actually ran.
            db.execute("UPDATE jobs SET status='cancelled', summary='사용자가 취소함', notified=1 WHERE id=? AND status=?", (job_id, status))
            return f'작업 {job_id} 취소됨 (대기열에서 제거).'
        if status == 'running':
            with self.children_lock:
                child = self.children.get(job_id)
            if not child:
                return f'작업 {job_id}은 시작 준비 중입니다. 잠시 후 다시 /cancel {job_id}를 시도하세요.'
            with self.cancel_lock:
                self.cancel_requested.add(job_id)
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            return f'작업 {job_id} 중지를 요청했습니다. 곧 취소 처리됩니다.'
        return f'작업 {job_id}은 이미 {status} 상태라 취소할 수 없습니다.'

    def diff_job(self, db, job_id):
        row = db.execute('SELECT project, commit_before, commit_after FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not row:
            return f'작업 {job_id}를 찾지 못했습니다.'
        before = row['commit_before']
        if not before:
            return f'작업 {job_id}: 커밋 정보가 없습니다 (아직 시작 전이거나 git 저장소가 아님).'
        after = row['commit_after'] or before
        if before == after:
            return f'작업 {job_id}: 커밋 변경 없음 ({before[:7]}).'
        try:
            project = self.project_path(row['project'])
        except (OSError, RuntimeError):
            return f'작업 {job_id}: 저장소 경로를 확인할 수 없습니다.'
        commits = subprocess.run(['git', '-C', str(project), 'log', '--oneline', f'{before}..{after}'],
                                 text=True, capture_output=True, timeout=10)
        stat = subprocess.run(['git', '-C', str(project), 'diff', '--stat', f'{before}..{after}'],
                              text=True, capture_output=True, timeout=10)
        return (f'작업 {job_id}: {before[:7]}..{after[:7]}\n'
                f'{commits.stdout.strip() or "(커밋 없음)"}\n\n'
                f'{stat.stdout.strip() or "(변경 통계 없음)"}')

    def usage_summary(self, db):
        window_start = time.time() - 7 * 86400
        rows = db.execute("""SELECT backend, COUNT(*) AS total,
            SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS done,
            SUM(limit_hits) AS hits
            FROM jobs WHERE created_at >= ? GROUP BY backend""", (window_start,)).fetchall()
        if not rows:
            return '최근 7일간 작업 기록이 없습니다.'
        lines = ['최근 7일 사용량:']
        for r in rows:
            lines.append(f'{r["backend"]}: 작업 {r["total"]}개 (완료 {r["done"]}개), 한도 도달 {r["hits"] or 0}회')
        return '\n'.join(lines)

    def poll(self):
        while not self.stop.is_set():
            try:
                with self.db() as db:
                    row = db.execute("SELECT value FROM meta WHERE key='offset'").fetchone()
                self.ingest(self.api('getUpdates', {'offset': int(row[0]) if row else 0,
                                                   'timeout': 25, 'allowed_updates': ['message', 'callback_query']}))
                self.send_outbox()
            except Exception:
                print('Telegram polling unavailable; retry in 30 seconds', flush=True)
                self.stop.wait(30)

    def send_outbox(self):
        with self.db() as db:
            rows = db.execute('SELECT * FROM outbox ORDER BY id').fetchall()
        for row in rows:
            payload = {'chat_id': row['chat'], 'text': row['text']}
            if row['markup']:
                payload['reply_markup'] = json.loads(row['markup'])
            sent = self.api('sendMessage', payload)
            with self.db() as db:
                if row['job_id'] is not None:
                    # Lets a later reply to *this* Telegram message resolve back to the job.
                    db.execute('INSERT OR REPLACE INTO job_messages(message_id, job_id) VALUES(?,?)',
                               (sent['message_id'], row['job_id']))
                db.execute('DELETE FROM outbox WHERE id=?', (row['id'],))

    def heartbeat(self, job_id, backend, start, stop_event):
        interval = self.cfg.get('heartbeat_seconds', 600)
        if not interval:
            return
        while not stop_event.wait(interval):
            elapsed = int((time.time() - start) / 60)
            with self.db() as db:
                self.queue_outbox(db, self.chat, f'작업 {job_id} [{backend}] 아직 실행 중입니다 ({elapsed}분 경과).', job_id=job_id)

    def watchdog(self, job_id, stop_event):
        # Safety net for a genuinely hung Claude/Codex process: without this, a stuck job would
        # occupy one of the limited concurrent worker slots forever, and since nobody may be
        # watching Telegram for hours, nobody would notice. 0/None disables it.
        timeout = self.cfg.get('job_timeout_seconds')
        if not timeout or stop_event.wait(timeout):
            return
        with self.timeout_lock:
            self.timeout_hit.add(job_id)
        with self.children_lock:
            child = self.children.get(job_id)
        if child:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def redact(self, text):
        for value in self.secrets.values():
            if len(value) >= 6:
                text = text.replace(value, '[REDACTED]')
        return re.sub(r'(?i)(?:sk-[\w-]+|\d{6,}:[\w-]{20,})', '[REDACTED]', text)

    def git_head(self, project):
        if not (Path(project) / '.git').exists():
            return None
        try:
            result = subprocess.run(['git', '-C', str(project), 'rev-parse', 'HEAD'],
                                    text=True, capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    def run_job(self, job):
        try:
            project = self.project_path(job['project'])
        except (OSError, RuntimeError) as exc:
            self.finish(job['id'], 'blocked', f'저장소 준비 오류: {exc}')
            return
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
        prompt = (f'프로젝트: {project}\n이 프로젝트에서만 작업하세요. RESUME_NOTE.md를 먼저 읽고 이어서 작업하세요. '
                  '질문에 대한 답변만 요구되고 파일 변경이 필요 없다면 답변 후 메모를 삭제하고 종료하세요. 이 경우 불필요한 커밋은 만들지 마세요. '
                  '중요 단계마다 메모를 갱신하세요. commit과 push 성공 후에만 메모를 삭제하세요. '
                  'RESUME_NOTE.md는 커밋 대상에서 제외하세요. '
                  '최종 응답은 래퍼가 텔레그램으로 전달하므로 완료 요약을 최종 응답으로 작성하세요.\n\n'
                  '원래 텔레그램 지시:\n' + job['instruction'])
        cmd = [self.cfg['codex_bin'], '-a', 'never', 'exec', '--ephemeral', '--json', '--color', 'never',
               '-s', self.cfg.get('sandbox', 'danger-full-access'), '-C', str(project),
               '-c', 'model_reasoning_effort=' + json.dumps(self.cfg.get('codex_reasoning_effort', 'xhigh')),
               '-c', 'sandbox_workspace_write.network_access=true',
               '-c', 'developer_instructions=' + json.dumps((HERE / 'worker_prompt.md').read_text(), ensure_ascii=False), '-']
        if not (project / '.git').exists():
            cmd.insert(cmd.index('-C'), '--skip-git-repo-check')
        backend = job['backend']
        workspace_root = self.cfg.get('workspace_root')
        if workspace_root:
            cmd[cmd.index('-C'):cmd.index('-C')] = ['--add-dir', workspace_root]
        if backend == 'claude':
            cmd = [self.cfg.get('claude_bin', '/usr/local/bin/claude'), '-p',
                   '--output-format', 'stream-json', '--verbose', '--no-session-persistence',
                   '--effort', self.cfg.get('claude_effort', 'xhigh'),
                   '--dangerously-skip-permissions', '--append-system-prompt',
                   (HERE / 'worker_prompt.md').read_text()]
            if workspace_root:
                cmd.extend(['--add-dir', workspace_root])
        child_env = os.environ.copy()
        if self.cfg.get('codex_home'):
            child_env['CODEX_HOME'] = self.cfg['codex_home']
        if backend == 'claude':
            child_env.pop('CLAUDECODE', None)
            if self.cfg.get('claude_config_dir'):
                child_env['CLAUDE_CONFIG_DIR'] = self.cfg['claude_config_dir']
        for key in self.secrets:
            if key.startswith('TELEGRAM_'):
                child_env.pop(key, None)
        limited, failed, completed, summary = False, False, False, ''
        commit_before = self.git_head(project)
        child = None
        heartbeat_stop = threading.Event()
        try:
            child = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, cwd=project, env=child_env,
                                     start_new_session=True)
            with self.children_lock:
                self.children[job['id']] = child
            if self.stop.is_set():
                os.killpg(child.pid, signal.SIGTERM)
            threading.Thread(target=self.heartbeat, args=(job['id'], backend, time.time(), heartbeat_stop), daemon=True).start()
            threading.Thread(target=self.watchdog, args=(job['id'], heartbeat_stop), daemon=True).start()
            child.stdin.write(prompt)
            child.stdin.close()
            for line in child.stdout:
                # Raw model/tool output is deliberately never persisted or sent to journald.
                try:
                    event = json.loads(line)
                except ValueError:
                    limited |= bool((CLAUDE_LIMIT if backend == 'claude' else LIMIT).search(line))
                    continue
                kind = event.get('type', '')
                if backend == 'claude':
                    if kind == 'result':
                        failed = bool(event.get('is_error')) or event.get('subtype') != 'success'
                        completed = not failed
                        summary = self.redact(event.get('result', ''))
                        if failed:
                            limited |= bool(CLAUDE_LIMIT.search(json.dumps(event)))
                    elif kind == 'assistant' and event.get('error'):
                        limited |= bool(CLAUDE_LIMIT.search(json.dumps(event)))
                    continue
                if kind in ('error', 'turn.failed'):
                    limited |= bool(LIMIT.search(json.dumps(event)))
                    failed |= kind == 'turn.failed'
                completed |= kind == 'turn.completed'
                item = event.get('item', {})
                if kind == 'item.completed' and item.get('type') == 'agent_message':
                    summary = self.redact(item.get('text', ''))
            rc = child.wait()
        except (OSError, BrokenPipeError):
            if child:
                child.wait()
            rc = 1
        finally:
            heartbeat_stop.set()
            with self.children_lock:
                self.children.pop(job['id'], None)
        with self.cancel_lock:
            cancelled = job['id'] in self.cancel_requested
            self.cancel_requested.discard(job['id'])
        with self.timeout_lock:
            timed_out = job['id'] in self.timeout_hit
            self.timeout_hit.discard(job['id'])
        commit_after = self.git_head(project)
        with self.db() as db:
            db.execute('UPDATE jobs SET commit_before=?, commit_after=? WHERE id=?', (commit_before, commit_after, job['id']))
        action_required = summary.lstrip().startswith('ACTION_REQUIRED:')
        if cancelled:
            self.finish(job['id'], 'cancelled', summary or '사용자가 취소함')
        elif timed_out:
            delay = min(self.cfg.get('retry_max_seconds', 3600),
                        self.cfg.get('retry_seconds', 900) * 2 ** min(job['attempts'], 8))
            timeout_minutes = self.cfg.get('job_timeout_seconds', 0) // 60
            with self.db() as db:
                db.execute("UPDATE jobs SET status='retry', due=? WHERE id=?", (time.time() + delay, job['id']))
                self.queue_outbox(db, self.chat, f'작업 {job["id"]} [{backend}] 시간 초과({timeout_minutes}분)로 중단했습니다. 재시도 예약됨.', job_id=job['id'])
        elif action_required:
            self.finish(job['id'], 'blocked', summary)
        elif rc == 0 and completed and not failed and not limited and not note.exists():
            self.finish(job['id'], 'done', summary or '작업 완료')
        elif limited or self.stop.is_set() or (rc == 0 and completed and note.exists()):
            delay = min(self.cfg.get('retry_max_seconds', 3600),
                        self.cfg.get('retry_seconds', 900) * 2 ** min(job['attempts'], 8))
            with self.db() as db:
                db.execute("UPDATE jobs SET status='retry', due=?, limit_hits=limit_hits+? WHERE id=?",
                           (time.time() + delay, 1 if limited else 0, job['id']))
        else:
            self.finish(job['id'], 'blocked', f'실행 오류(exit={rc}). 인증/CLI/권한 점검 필요; 메모 유지')

    def project_path(self, project):
        if project in self.cfg['projects']:
            return Path(self.cfg['projects'][project]).resolve()
        if not project.startswith('github:'):
            raise RuntimeError('Unknown project')
        repo = project.removeprefix('github:')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
            raise RuntimeError('Invalid repository')
        target = Path(self.cfg.get('repositories_dir', '/opt/projects')) / repo
        if target.exists():
            return target.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        cloned = subprocess.run([self.cfg.get('gh_bin', '/usr/bin/gh'), 'repo', 'clone', repo, str(target)], text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if cloned.returncode or not target.is_dir():
            raise RuntimeError('Repository clone failed')
        return target.resolve()

    def finish(self, uid, status, summary):
        with self.db() as db:
            db.execute('UPDATE jobs SET status=?,summary=? WHERE id=?', (status, summary, uid))

    def claim_job(self):
        # Claiming (select + mark 'running') must be atomic across worker threads so two
        # workers can never pick the same job, or two jobs from the same project at once.
        with self.claim_lock:
            with self.db() as db:
                job = db.execute("""SELECT * FROM jobs j WHERE status IN ('queued','retry') AND due<=?
                  AND NOT EXISTS (SELECT 1 FROM jobs k WHERE k.project=j.project AND k.id<j.id
                  AND k.status IN ('queued','retry','running','blocked')) ORDER BY id LIMIT 1""", (time.time(),)).fetchone()
                if job:
                    db.execute("UPDATE jobs SET status='running', attempts=attempts+1 WHERE id=?", (job['id'],))
        return job

    def work_once(self):
        job = self.claim_job()
        if job:
            self.run_job(job)
        return bool(job)

    def worker_loop(self):
        while not self.stop.is_set():
            if not self.work_once():
                self.stop.wait(2)

    def notify(self):
        with self.db() as db:
            rows = db.execute("SELECT * FROM jobs WHERE status IN ('done','blocked','cancelled') AND notified=0").fetchall()
        for row in rows:
            try:
                message = f"작업 {row['id']} [{row['backend']}: {row['status']}]\n{row['summary']}"
                with self.db() as db:
                    for start in range(0, len(message), 1800):
                        sent = self.api('sendMessage', {'chat_id': row['chat'], 'text': message[start:start + 1800]})
                        # Any chunk can be the one the user replies to, so a follow-up
                        # instruction resolves back to this job regardless of which they pick.
                        db.execute('INSERT OR REPLACE INTO job_messages(message_id, job_id) VALUES(?,?)', (sent['message_id'], row['id']))
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
            with self.children_lock:
                children = list(self.children.values())
            for child in children:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        threading.Thread(target=self.poll, daemon=True).start()
        # Multiple workers let independent projects/backends run at the same time instead of
        # a new Telegram command sitting stuck behind whatever job is currently executing.
        workers = [threading.Thread(target=self.worker_loop, daemon=True)
                   for _ in range(max(1, self.cfg.get('max_concurrent_jobs', 3)))]
        for worker in workers:
            worker.start()
        while not self.stop.is_set():
            self.notify()
            self.stop.wait(2)
        for worker in workers:
            worker.join()


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    Service(json.loads(Path(args.config).read_text())).run()


if __name__ == '__main__':
    main()
