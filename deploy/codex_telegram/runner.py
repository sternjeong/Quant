#!/usr/bin/env python3
"""Durable Telegram polling and concurrent Codex/Claude job supervisor (stdlib only)."""
import argparse
import ast
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request

HERE = Path(__file__).resolve().parent
LIMIT = re.compile(r"usage_limit_(?:reached|exceeded)|usage limit|rate_limit_exceeded|rate limit|too many requests|\b429\b", re.I)
CLAUDE_LIMIT = re.compile(r"usage limit|rate.?limit|hit your limit|out of extra usage|\b429\b", re.I)

# 텔레그램 /processes 가 보여 주고 켜고 끄는 잡 목록은 core/process_registry.py 의 PROCESS_REGISTRY 한 곳에서만
# 정의한다. 이 파일은 core/를 임포트하지 않는 stdlib-only 프로세스(시스템 python3)라서 그 파일을 import 하지
# 않고 ast 로 파싱해 딕셔너리 리터럴만 읽는다(load_process_catalog). 그래서 레지스트리에 잡을 추가하면 여기엔
# 손대지 않아도 텔레그램 목록에 자동으로 나타난다. tests/test_telegram_process_catalog_sync.py 가
# "러너가 보여 주는 키 == PROCESS_REGISTRY 키 == core.job_schedule 의 process_key" 를 검증하므로
# 레지스트리를 리터럴이 아닌 형태로 바꾸는 등 러너가 못 읽게 되면 테스트가 실패한다.
# 실제 on/off 상태는 core.process_registry와 같은 파일(data/process_toggles.json)을 같은 형식으로 공유한다.
PROCESS_REGISTRY_PATH = HERE.parent.parent / 'core' / 'process_registry.py'
PROCESS_CATEGORIES = (('alert', '🔔 알림'), ('research', '🔬 연구·기록'), ('maintenance', '🧰 유지보수'))
# Telegram sendMessage 한도는 4096자다. 여유를 두고 이 길이로 나눈다(queue_outbox의 절단 길이와 같음).
TELEGRAM_TEXT_LIMIT = 3900


def load_process_catalog(path=None):
    """core/process_registry.py 의 PROCESS_REGISTRY 를 import 없이 읽어 정의 순서대로 돌려준다.

    Returns: [{'key','label','description','category','default_enabled','places_orders'}, ...]
    Raises: OSError(파일 없음), SyntaxError/ValueError(리터럴이 아니거나 형식이 다름).
    """
    path = Path(path or PROCESS_REGISTRY_PATH)
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    registry = None
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = node.targets
        else:
            continue
        if node.value is not None and any(isinstance(t, ast.Name) and t.id == 'PROCESS_REGISTRY' for t in targets):
            registry = ast.literal_eval(node.value)
    if not isinstance(registry, dict) or not registry:
        raise ValueError('PROCESS_REGISTRY 딕셔너리 리터럴을 찾지 못했습니다')
    catalog = []
    for key, meta in registry.items():
        if not isinstance(key, str) or not isinstance(meta, dict) or 'label' not in meta:
            raise ValueError(f'PROCESS_REGISTRY 항목 형식이 다릅니다: {key!r}')
        catalog.append({'key': key, 'label': str(meta['label']), 'description': str(meta.get('description', '')),
                        'category': str(meta.get('category', '')),
                        'default_enabled': bool(meta.get('default_enabled', True)),
                        'places_orders': bool(meta.get('places_orders', False))})
    return catalog


def split_text(text, limit=None):
    """text를 limit 이하 조각으로 나눈다. 가능한 한 줄 경계에서 자르고, 한 줄이 limit보다 길면 그 줄만 강제로 자른다."""
    limit = limit or TELEGRAM_TEXT_LIMIT
    chunks, current = [], ''
    for line in text.split('\n'):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ''
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f'{current}\n{line}' if current else line
        if current and len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current or not chunks:
        chunks.append(current)
    return chunks
HYPOTHESIS_ID = re.compile(r'^H-\d{8}-\d{3}$')
# core.agent_budget.ROLES / MODEL_CHOICES 와 같은 값(이 러너는 core/ 를 import 하지 않는다 — 동기화는 테스트가 잡는다).
AGENT_ROLES = [('scout', 'Scout 아이디어 수집', 'haiku'), ('writer', 'Writer 가설 작성', 'opus'),
               ('implementer', 'Implementer 코드 작성', 'sonnet'), ('critic', 'Critic 코드 검증', 'opus'),
               ('postmortem', 'Post-mortem 실패 교훈', 'sonnet')]
AGENT_MODEL_CHOICES = ('haiku', 'sonnet', 'opus')


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
            if 'finished_at' not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN finished_at REAL NOT NULL DEFAULT 0")
            db.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('backend',?)", (cfg.get('default_backend', 'claude'),))
            db.execute('CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY, chat TEXT, text TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY, chat TEXT, instruction TEXT, repo TEXT, state TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS repo_choices(request_id INTEGER, number INTEGER, repo TEXT, PRIMARY KEY(request_id, number))')
            db.execute('CREATE TABLE IF NOT EXISTS job_messages(message_id INTEGER PRIMARY KEY, job_id INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS ideas(id INTEGER PRIMARY KEY, chat TEXT, text TEXT, created_at REAL)')
            outbox_columns = {row[1] for row in db.execute('PRAGMA table_info(outbox)')}
            if 'markup' not in outbox_columns:
                db.execute('ALTER TABLE outbox ADD COLUMN markup TEXT')
            if 'job_id' not in outbox_columns:
                db.execute('ALTER TABLE outbox ADD COLUMN job_id INTEGER')

    def db(self):
        db = sqlite3.connect(self.state / 'queue.sqlite', timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def quant_root(self):
        """Quant 저장소의 실제 경로. 설정에 quant가 없으면 default_project, 그것도 없으면 /opt/quant."""
        default_project = self.cfg.get('default_project', '')
        return Path(self.cfg['projects'].get('quant', self.cfg['projects'].get(default_project, '/opt/quant'))).resolve()

    def read_json_file(self, path, default):
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return default

    def write_json_file(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(path)

    def process_toggles_path(self):
        """core.process_registry.TOGGLE_STATE_PATH와 동일한 파일 -- quant_root() 아래 data/ 를 써서
        스케줄러(core.process_registry.is_enabled)와 항상 같은 파일을 본다."""
        root = self.quant_root()
        return root / 'data' / 'process_toggles.json'

    def is_process_enabled(self, key, default):
        state = self.read_json_file(self.process_toggles_path(), {})
        return bool(state.get(key, {}).get('enabled', default))

    def set_process_enabled(self, key, enabled):
        path = self.process_toggles_path()
        state = self.read_json_file(path, {})
        state[key] = {'enabled': enabled, 'updated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                      'actor': f'telegram:{self.chat}'}
        self.write_json_file(path, state)

    def process_catalog(self):
        """레지스트리 목록. 파싱에 실패하면 (None, 이유)를 돌려줘 텔레그램 폴링이 죽지 않게 한다."""
        try:
            return load_process_catalog(self.cfg.get('process_registry_path')), ''
        except (OSError, SyntaxError, ValueError) as exc:
            return None, f'{type(exc).__name__}: {str(exc)[:200]}'

    def agent_models_path(self):
        return self.quant_root() / 'data' / 'agent_models.json'

    def agent_model(self, role, default):
        entry = self.read_json_file(self.agent_models_path(), {}).get(role)
        model = entry.get('model') if isinstance(entry, dict) else entry
        return model if model in AGENT_MODEL_CHOICES else default

    def models_text_and_markup(self):
        lines = ['🤖 에이전트 역할별 모델 (탭하면 haiku → sonnet → opus 순환, 다음 03:00 배치부터 적용)', '']
        rows = []
        for index, (role, label, default) in enumerate(AGENT_ROLES):
            model = self.agent_model(role, default)
            lines.append(f'• {label}: {model}' + (' (기본)' if model == default else ''))
            rows.append([{'text': f'{label}: {model} → 바꾸기', 'callback_data': f'm:{index}'}])
        lines.append('')
        lines.append('비싼 모델일수록 예산(하룻밤 $15·주간 $60)이 빨리 찹니다. 허브 /research 에서도 바꿀 수 있습니다.')
        return '\n'.join(lines), {'inline_keyboard': rows}

    def handle_model_cycle_callback(self, db, chat, data, callback):
        try:
            role, label, default = AGENT_ROLES[int(data.split(':', 1)[1])]
        except (ValueError, IndexError):
            return
        current = self.agent_model(role, default)
        new = AGENT_MODEL_CHOICES[(AGENT_MODEL_CHOICES.index(current) + 1) % len(AGENT_MODEL_CHOICES)]
        state = self.read_json_file(self.agent_models_path(), {})
        state = state if isinstance(state, dict) else {}
        state[role] = {'model': new, 'updated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                       'actor': f'telegram:{self.chat}'}
        self.write_json_file(self.agent_models_path(), state)
        text, markup = self.models_text_and_markup()
        self.queue_outbox(db, chat, f'🔁 {label}: {current} → {new}\n\n' + text, markup)
        try:
            self.api('answerCallbackQuery', {'callback_query_id': callback['id'], 'text': f'{label}: {new}'})
        except Exception:
            pass

    def process_count_text(self):
        """/help 에 쓸 실제 잡 개수('27개'). 레지스트리를 못 읽으면 '(개수 확인 불가)'."""
        catalog, _ = self.process_catalog()
        return f'{len(catalog)}개' if catalog is not None else '(개수 확인 불가)'

    def process_entry(self, key):
        catalog, _ = self.process_catalog()
        return next((entry for entry in catalog or () if entry['key'] == key), None)

    def process_category_message(self, catalog, category, title):
        """카테고리 하나의 목록 텍스트와 버튼. 항목이 없으면 None."""
        entries = [entry for entry in catalog if entry['category'] == category]
        if not entries:
            return None
        lines, rows = [], []
        on = 0
        for entry in entries:
            enabled = self.is_process_enabled(entry['key'], entry['default_enabled'])
            on += enabled
            order_mark = ' 💸' if entry['places_orders'] else ''
            lines.append(f'{"✅" if enabled else "⏸"} {entry["label"]}{order_mark}\n    {entry["key"]}')
            action = '끄기' if enabled else ('켜기(확인 필요)' if entry['places_orders'] else '켜기')
            rows.append([{'text': f'{action} · {entry["label"]}', 'callback_data': f'p:{entry["key"]}'}])
        header = f'{title} — 켜짐 {on}/{len(entries)}'
        return header + '\n' + '\n'.join(lines), {'inline_keyboard': rows}

    def processes_messages(self, only_category=None):
        """/processes 응답을 [(text, markup), ...]으로 만든다. 카테고리별 한 메시지, 길면 줄 경계로 나누고
        버튼은 그 카테고리의 마지막 조각에 붙인다. 모든 조각은 TELEGRAM_TEXT_LIMIT 이하다."""
        catalog, error = self.process_catalog()
        if catalog is None:
            return [(f'잡 목록(core/process_registry.py)을 읽지 못했습니다 — {error}\n'
                     '토글 파일은 그대로입니다. 개발 요청으로 확인하세요.', None)]
        known = {c for c, _ in PROCESS_CATEGORIES}
        categories = list(PROCESS_CATEGORIES) + [(c, f'📦 {c or "기타"}') for c in
                                                 dict.fromkeys(e['category'] for e in catalog) if c not in known]
        messages = []
        if only_category is None:
            on = sum(self.is_process_enabled(e['key'], e['default_enabled']) for e in catalog)
            messages.append((f'⚙️ 자동 잡 {len(catalog)}개 — 켜짐 {on} · 꺼짐 {len(catalog) - on}\n'
                             '버튼을 누르면 켜고 끕니다. 글자로: /processes on 키 · /processes off 키\n'
                             '💸 = 주문을 내는 잡(켤 때 한 번 더 확인)', None))
        for category, title in categories:
            if only_category is not None and category != only_category:
                continue
            built = self.process_category_message(catalog, category, title)
            if not built:
                continue
            text, markup = built
            chunks = split_text(text)
            messages.extend((chunk, None) for chunk in chunks[:-1])
            messages.append((chunks[-1], markup))
        return messages

    @staticmethod
    def with_notice(notice, messages):
        """결과 한 줄을 첫 메시지 앞에 붙인다. 붙이면 한도를 넘을 때만 별도 메시지로 앞에 둔다."""
        first_text, first_markup = messages[0]
        combined = notice + '\n\n' + first_text
        if len(combined) <= TELEGRAM_TEXT_LIMIT:
            return [(combined, first_markup)] + messages[1:]
        return [(notice, None)] + messages

    def confirm_process_message(self, entry):
        text = (f'⚠️ 정말 켜시겠습니까? "{entry["label"]}"은(는) 자동으로 주문을 제출하는 잡입니다.\n'
                f'설명: {entry["description"][:300]}\n'
                f'켜려면 아래 버튼을 누르거나 /processes on {entry["key"]} confirm 을 보내세요. '
                '(끄기는 확인 없이 바로 됩니다)')
        markup = {'inline_keyboard': [[{'text': f'⚠️ 정말 켜기 · {entry["label"]}',
                                        'callback_data': f'pc:{entry["key"]}'}]]}
        return text, markup

    def apply_process_toggle(self, key, enabled, confirmed=False):
        """켜기/끄기를 적용하고 (레지스트리 항목, 확인요청 여부)를 돌려준다. 주문을 내는 잡을 켤 때 confirmed가
        아니면 상태를 바꾸지 않는다. 알 수 없는 키면 (None, False)."""
        entry = self.process_entry(key)
        if entry is None:
            return None, False
        if enabled and entry['places_orders'] and not confirmed:
            return entry, True
        self.set_process_enabled(key, enabled)
        return entry, False

    def process_command(self, db, rest):
        """/processes [on|off 키 [confirm]]. 목록은 여러 메시지일 수 있어 앞 조각은 바로 큐에 넣고
        마지막 (text, markup)을 돌려준다."""
        args = rest.split()
        if not args:
            messages = self.processes_messages()
        else:
            action = args[0].lower()
            key = args[1] if len(args) > 1 else ''
            confirmed = len(args) > 2 and args[2].lower() == 'confirm'
            if action not in ('on', 'off') or not key or len(args) > 3 or (len(args) == 3 and not confirmed):
                return ('사용법: /processes (목록) · /processes on 키 · /processes off 키\n'
                        '주문을 내는 잡은 /processes on 키 confirm 으로 켭니다.'), None
            entry, needs_confirm = self.apply_process_toggle(key, action == 'on', confirmed)
            if entry is None:
                return f'알 수 없는 잡: {key}\n/processes 로 키 목록을 확인하세요.', None
            if needs_confirm:
                return self.confirm_process_message(entry)
            done = f'{"✅ 켬" if action == "on" else "⏸ 끔"}: {entry["label"]} ({key})'
            messages = self.with_notice(done, self.processes_messages(entry['category']))
        for text, markup in messages[:-1]:
            self.queue_outbox(db, self.chat, text, markup=markup)
        return messages[-1]

    def news_digest_status(self, requested_ticker=''):
        """Quant DB의 최신 뉴스 요약을 stdlib sqlite로 읽는다.

        listener는 의도적으로 프로젝트 가상환경/SQLAlchemy에 의존하지 않는다. 뉴스 수집은
        스케줄러가 맡고 이 명령은 저장된 결과만 읽으므로 Telegram polling을 막지 않는다.
        """
        ticker = requested_ticker.strip().upper()
        if ticker and not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}', ticker):
            return '사용법: /news 또는 /news XLK'
        root = self.quant_root()
        db_path = root / 'data' / 'quant.db'
        if not db_path.is_file():
            return '뉴스 DB가 아직 만들어지지 않았습니다. 서버 배포 후 첫 일일 수집을 기다리거나 웹의 뉴스 리서치에서 실행하세요.'
        try:
            with sqlite3.connect(db_path, timeout=5) as db:
                db.row_factory = sqlite3.Row
                if ticker:
                    rows = db.execute(
                        'SELECT ticker, article_count, summary, created_at FROM news_ticker_digests '
                        'WHERE ticker=? ORDER BY id DESC LIMIT 1', (ticker,)
                    ).fetchall()
                else:
                    rows = db.execute(
                        'SELECT ticker, article_count, summary, created_at FROM news_ticker_digests '
                        'WHERE id IN (SELECT MAX(id) FROM news_ticker_digests GROUP BY ticker) '
                        'ORDER BY created_at DESC LIMIT 12'
                    ).fetchall()
        except sqlite3.Error:
            return '뉴스 요약 테이블이 아직 준비되지 않았습니다. 첫 배포·수집 후 /news로 다시 확인하세요.'
        if not rows:
            return (f'{ticker} 뉴스 요약이 아직 없습니다.' if ticker else
                    '아직 뉴스 요약이 없습니다. 웹의 뉴스 리서치에서 ‘지금 수집·요약’을 누르거나 다음 일일 보고를 기다리세요.')
        lines = ['📰 최신 티커 뉴스 요약']
        for row in rows:
            summary = re.sub(r'\s+', ' ', row['summary'] or '').replace('•', '')[:260]
            lines.append(f"• {row['ticker']} ({row['article_count']}건): {summary}")
        lines.append('전체 출처 링크는 매일 첨부되는 HTML 또는 웹의 뉴스 리서치 페이지에서 확인하세요.')
        return '\n'.join(lines)

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
                mine = str(chat.get('id')) == self.chat and chat.get('type') == 'private'
                # 사진·파일은 text가 없어서 예전에는 통째로 버려졌다. 이제 notes/ 에 저장한다(무지성 커밋의 한 갈래).
                if mine and not instruction and (msg.get('photo') or msg.get('document')):
                    self.queue_outbox(db, self.chat, self.store_message_media(msg))
                    db.execute("INSERT INTO meta VALUES('offset',?) ON CONFLICT(key) DO UPDATE SET value=max(cast(value as integer),cast(excluded.value as integer))", (str(uid + 1),))
                    continue
                if mine and instruction:
                    selected = db.execute("SELECT value FROM meta WHERE key='backend'").fetchone()
                    backend = selected[0] if selected else 'codex'
                    # Accept a newline after the command as well as a space.
                    parts = instruction.split(maxsplit=1)
                    command = parts[0].split('@')[0]
                    rest = parts[1] if len(parts) > 1 else ''
                    reply = None
                    reply_job_id = None
                    reply_markup = None
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
                    elif command == '/note':
                        reply = self.save_note(rest)[0]
                    elif command == '/progress':
                        reply = self.append_progress(rest)
                    elif command == '/cat':
                        reply = self.cat_file(rest)
                    elif command == '/log':
                        reply = self.repo_log(rest)
                    elif command == '/repo':
                        reply = self.repo_state()
                    elif command == '/usage':
                        reply = self.usage_summary(db)
                    elif command == '/digest':
                        reply = self.digest_summary(db)
                    elif command == '/news':
                        reply = self.news_digest_status(rest)
                    elif command == '/processes':
                        reply, reply_markup = self.process_command(db, rest)
                    elif command == '/models':
                        reply, reply_markup = self.models_text_and_markup()
                    elif command == '/idea' and rest.strip():
                        db.execute('INSERT OR IGNORE INTO ideas(id,chat,text,created_at) VALUES(?,?,?,?)',
                                   (uid, self.chat, rest.strip(), time.time()))
                        count = db.execute('SELECT COUNT(*) FROM ideas WHERE chat=?', (self.chat,)).fetchone()[0]
                        reply = f'아이디어 저장됨 (대기 {count}개). /ideas로 확인하세요.'
                    elif command == '/ideas' and rest.strip() == '비우기':
                        db.execute('DELETE FROM ideas WHERE chat=?', (self.chat,))
                        reply = '저장된 아이디어를 모두 지웠습니다.'
                    elif command == '/ideas':
                        rows = db.execute('SELECT text FROM ideas WHERE chat=? ORDER BY id', (self.chat,)).fetchall()
                        reply = ('저장된 아이디어가 없습니다.' if not rows else
                                 '\n'.join(f'{i}. {r["text"]}' for i, r in enumerate(rows, 1)))
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
                                 '/note 메모: 비공개 저장소에 바로 저장 (사진·파일도 보내면 저장됨)\n'
                                 '/progress 내용: 공개 저장소 PROGRESS.md에 바로 커밋·푸시\n'
                                 '/cat 경로 [줄수]: 저장소 파일 끝부분 보기 (예: /cat PROGRESS.md 30)\n'
                                 '/log [개수]: 최근 커밋 요약\n'
                                 '/repo: VM 저장소 상태(HEAD·origin과의 차이·미커밋 파일)\n'
                                 '/digest: 마지막 확인 이후 끝난 작업 + 지금 대기/실행 중인 작업 한눈에 보기\n'
                                 '/news 또는 /news XLK: 최신 티커 뉴스 요약 (원문 링크는 일일 HTML/웹에서 확인)\n'
                                 '/idea 메모: Claude/Codex 호출 없이 아이디어만 저장\n'
                                 '/ideas: 저장된 아이디어 목록, /ideas 비우기: 전체 삭제\n'
                                 '/retry 작업ID: blocked 작업 재개\n'
                                 f'/processes: 자동 잡 {self.process_count_text()} on/off 목록 (카테고리별, 버튼 탭으로 켜고 끄기)\n'
                                 '/processes on 키 · /processes off 키: 글자로 켜고 끄기 '
                                 '(주문을 내는 잡은 켤 때 확인 단계: /processes on 키 confirm)\n'
                                 '/models: AI 에이전트 역할별 모델 바꾸기 (haiku/sonnet/opus)\n'
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
                        self.queue_outbox(db, self.chat, reply, markup=reply_markup, job_id=reply_job_id)
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

    def handle_process_toggle_callback(self, db, chat, data, callback):
        """p:키 = 켜짐↔꺼짐 전환(주문을 내는 잡을 켜는 경우엔 확인 버튼만 보냄), pc:키 = 확인 후 켜기.
        버튼은 순번이 아니라 키를 담는다 — 레지스트리 순서가 바뀌어도 옛 메시지의 버튼이 엉뚱한 잡을
        바꾸지 않는다(모르는 키·옛 숫자 버튼은 상태를 바꾸지 않고 무시)."""
        kind, _, key = data.partition(':')
        entry = self.process_entry(key)
        if entry is None:
            answer = '목록이 바뀌었습니다. /processes 로 다시 여세요.'
        else:
            if kind == 'pc':
                enabled, needs_confirm = True, False
                self.set_process_enabled(key, True)
            else:
                enabled = not self.is_process_enabled(key, entry['default_enabled'])
                _, needs_confirm = self.apply_process_toggle(key, enabled)
            if needs_confirm:
                text, markup = self.confirm_process_message(entry)
                self.queue_outbox(db, chat, text, markup)
                answer = '확인이 필요합니다'
            else:
                notice = f'{"✅ 켬" if enabled else "⏸ 끔"}: {entry["label"]}'
                for text, markup in self.with_notice(notice, self.processes_messages(entry['category'])):
                    self.queue_outbox(db, chat, text, markup)
                answer = f'{entry["label"]}: {"켜짐" if enabled else "꺼짐"}'
        try:
            self.api('answerCallbackQuery', {'callback_query_id': callback['id'], 'text': answer[:190]})
        except Exception:
            pass

    def run_hypothesis_admin(self, action, hid):
        """scripts/hypothesis_admin.py 를 프로젝트 venv 로 실행한다(이 러너는 core/ 를 import 하지 않는 stdlib 전용)."""
        root = self.quant_root()
        python = root / '.venv' / 'bin' / 'python'
        cmd = [str(python if python.exists() else sys.executable), str(root / 'scripts' / 'hypothesis_admin.py'), action, hid]
        try:
            proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f'{type(exc).__name__}'
        return proc.returncode == 0, (proc.stdout + proc.stderr).strip()[-300:]

    def handle_hypothesis_callback(self, db, chat, data, callback):
        try:
            _, action, hid = data.split(':', 2)
        except ValueError:
            return
        if action not in ('promote', 'retire') or not HYPOTHESIS_ID.match(hid):
            return
        ok, detail = self.run_hypothesis_admin(action, hid)
        if ok and action == 'promote':
            text = (f'✅ {hid} paper 편입 승인. 다음 자동 주문(화~토 06:10 KST)부터 research 슬리브에 들어갑니다.\n'
                    f'자동 주문이 꺼져 있으면 /processes 에서 "챔피언 paper 자동 주문"을 켜야 실제로 제출됩니다.')
        elif ok:
            text = f'🗑 {hid} 종료. paper 에 들어가 있었다면 다음 자동 주문에서 정리됩니다.'
        else:
            text = f'⚠️ {hid} {action} 실패: {detail}'
        self.queue_outbox(db, chat, text)
        try:
            message = callback.get('message') or {}
            if ok and message.get('message_id'):
                self.api('editMessageReplyMarkup', {'chat_id': chat, 'message_id': message['message_id'],
                                                    'reply_markup': {'inline_keyboard': []}})
            self.api('answerCallbackQuery', {'callback_query_id': callback['id'], 'text': '처리됨' if ok else '실패'})
        except Exception:
            pass

    def handle_callback(self, db, callback):
        chat = str(callback.get('message', {}).get('chat', {}).get('id', ''))
        if chat != self.chat:
            return
        data = callback.get('data', '')
        if data.startswith(('p:', 'pc:')):
            # /processes 토글 버튼 -- request_id 기반 대화 상태가 필요 없는 단발성 액션이라
            # 아래 request_id 기반 콜백들과는 별도 경로로 먼저 처리한다.
            self.handle_process_toggle_callback(db, chat, data, callback)
            return
        if data.startswith('m:'):
            # /models 의 역할별 모델 순환 버튼
            self.handle_model_cycle_callback(db, chat, data, callback)
            return
        if data.startswith('h:'):
            # 가설 승격 후보 알림의 [paper 편입]/[종료] 버튼 (core.hypothesis_shadow.approval_buttons)
            self.handle_hypothesis_callback(db, chat, data, callback)
            return
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
            db.execute("UPDATE jobs SET status='cancelled', summary='사용자가 취소함', notified=1, finished_at=? WHERE id=? AND status=?",
                       (time.time(), job_id, status))
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

    # ---- 무지성 커밋: /note(비공개), /progress(공개) — LLM을 부르지 않는다 ---------------------------
    # docs/TELEGRAM_REPO_BRIDGE_SPEC.md 3-1 참고.
    #  /note    → /opt/quant/notes/YYYY-MM/DD.md 에 append. 이 경로는 공개 저장소에서 .gitignore로 막혀 있고,
    #             야간 백업(deploy/backup_vm.py)이 **비공개** 저장소로 가져간다. 폰에서 급히 친 메모의 안전한 기본값.
    #  /progress → 공개 저장소의 PROGRESS.md 끝에 append 후 즉시 commit+push. 작업 디렉터리를 전혀 건드리지
    #             않도록 git 배관(hash-object/read-tree/commit-tree)으로 origin/main 위에 커밋을 만든다 —
    #             VM 워킹트리에는 리서치 에이전트의 미커밋 수정이 늘 있어서 checkout/rebase 류를 쓰면 위험하다.
    # 비밀 패턴은 deploy/backup_vm.py의 것과 같은 의도의 축약본이다(러너는 stdlib만 쓰는 독립 프로세스라 공유하지 않는다).

    NOTE_MAX_CHARS = 4000
    ATTACHMENT_MAX_BYTES = 20 * 1024 * 1024  # 텔레그램 봇 다운로드 상한
    SECRET_PATTERNS = (
        r'-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----',
        r'\bghp_[A-Za-z0-9]{30,}', r'\bgithub_pat_[A-Za-z0-9_]{30,}',
        r'\bsk-ant-[A-Za-z0-9_-]{20,}', r'\bsk-[A-Za-z0-9]{32,}',
        r'\bAKIA[0-9A-Z]{16}\b', r'\bxox[baprs]-[A-Za-z0-9-]{10,}',
        r'\bAIza[0-9A-Za-z_-]{35}\b', r'\b\d{8,10}:[A-Za-z0-9_-]{35}\b',
    )

    def looks_secret(self, text):
        """비밀처럼 보이면 그 사실만 알려준다(어떤 값인지는 절대 돌려주지 않는다)."""
        return any(re.search(pattern, text) for pattern in self.SECRET_PATTERNS)

    def notes_dir(self):
        return self.quant_root() / 'notes'

    def save_note(self, text, when=None):
        """/note — 비공개 경로에 append. (응답문자열, 저장경로 또는 None)"""
        text = (text or '').strip()
        if not text:
            return ('사용법: /note <메모>  — 사진이나 파일을 보내면서 캡션에 /note 를 써도 됩니다.', None)
        if len(text) > self.NOTE_MAX_CHARS:
            return (f'너무 깁니다({len(text):,}자). {self.NOTE_MAX_CHARS:,}자 이하로 나눠 보내주세요.', None)
        if self.looks_secret(text):
            return ('비밀(키·토큰)처럼 보이는 내용이 있어 저장하지 않았습니다. 값은 화면에 다시 띄우지 않습니다.', None)
        stamp = when or time.localtime()
        target = self.notes_dir() / time.strftime('%Y-%m', stamp) / (time.strftime('%d', stamp) + '.md')
        target.parent.mkdir(parents=True, exist_ok=True)
        entry = f"\n## {time.strftime('%H:%M', stamp)}\n{text}\n"
        with target.open('a', encoding='utf-8') as handle:
            handle.write(entry)
        rel = target.relative_to(self.quant_root())
        return (f'메모 저장: {rel}\n오늘 밤 백업이 비공개 저장소로 올립니다(공개 저장소에는 올라가지 않습니다).', target)

    def save_attachment(self, file_id, filename, caption=''):
        """텔레그램이 보낸 사진/파일을 notes/attachments/ 에 내려받는다. (응답문자열, 저장경로 또는 None)"""
        try:
            meta = self.api('getFile', {'file_id': file_id})
        except Exception as exc:  # noqa: BLE001 — 네트워크/권한 등 어떤 실패든 사용자에게 알린다
            return (f'첨부 정보를 가져오지 못했습니다: {type(exc).__name__}', None)
        size = meta.get('file_size') or 0
        if size > self.ATTACHMENT_MAX_BYTES:
            return (f'파일이 너무 큽니다({size/1e6:.1f}MB). 20MB 이하만 저장합니다.', None)
        remote_path = meta.get('file_path')
        if not remote_path:
            return ('첨부 경로를 확인하지 못했습니다.', None)
        url = f'https://api.telegram.org/file/bot{self.token}/{remote_path}'
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                blob = response.read(self.ATTACHMENT_MAX_BYTES + 1)
        except Exception as exc:  # noqa: BLE001
            return (f'첨부를 내려받지 못했습니다: {type(exc).__name__}', None)
        if len(blob) > self.ATTACHMENT_MAX_BYTES:
            return ('파일이 너무 큽니다(20MB 초과).', None)
        suffix = Path(remote_path).suffix or Path(filename or '').suffix or '.bin'
        stamp = time.localtime()
        safe_stem = re.sub(r'[^A-Za-z0-9_.-]', '_', (filename or 'attachment').rsplit('.', 1)[0])[:40]
        target = (self.notes_dir() / 'attachments' /
                  f"{time.strftime('%Y%m%d-%H%M%S', stamp)}-{safe_stem}{suffix}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        rel = target.relative_to(self.quant_root())
        note_line = f"첨부: `{rel.name}`" + (f"\n{caption}" if caption else '')
        self.save_note(note_line, stamp)
        return (f'첨부 저장: {rel} ({len(blob)/1e6:.1f}MB)\n오늘 밤 백업이 비공개 저장소로 올립니다.', target)

    def store_message_media(self, msg):
        """사진/파일이 붙은 메시지를 notes/ 로 저장한다. 캡션은 메모 본문으로 같이 남긴다."""
        caption = (msg.get('caption') or '').strip()
        # 캡션이 /note 로 시작하면 그 뒤만 메모 본문으로 쓴다.
        if caption.split(maxsplit=1)[:1] == ['/note']:
            caption = caption.split(maxsplit=1)[1] if len(caption.split(maxsplit=1)) > 1 else ''
        document = msg.get('document')
        if document:
            return self.save_attachment(document.get('file_id'), document.get('file_name', 'file'), caption)[0]
        photos = msg.get('photo') or []
        if photos:
            largest = max(photos, key=lambda item: item.get('file_size') or 0)  # 텔레그램은 여러 해상도를 준다
            return self.save_attachment(largest.get('file_id'), 'photo.jpg', caption)[0]
        return '저장할 첨부를 찾지 못했습니다.'

    def append_progress(self, text):
        """/progress — 공개 저장소 PROGRESS.md 끝에 append하고 즉시 커밋·푸시. 워킹트리는 건드리지 않는다."""
        text = (text or '').strip()
        if not text:
            return '사용법: /progress <기록할 내용>  — 공개 저장소의 PROGRESS.md에 바로 커밋됩니다.'
        if len(text) > self.NOTE_MAX_CHARS:
            return f'너무 깁니다({len(text):,}자). {self.NOTE_MAX_CHARS:,}자 이하로 줄여주세요.'
        if self.looks_secret(text):
            return '비밀(키·토큰)처럼 보이는 내용이 있어 커밋하지 않았습니다. 이 저장소는 공개입니다.'
        last_error = ''
        for attempt in range(2):  # 그 사이 origin이 움직이면 한 번 다시 만든다
            ok, detail = self.push_progress_entry(text)
            if ok:
                return (f'PROGRESS.md에 커밋했습니다 ({detail}).\n'
                        '공개 저장소이며, 5분 안에 자동배포가 VM으로 가져갑니다.')
            last_error = detail
        return f'커밋하지 못했습니다: {last_error}'

    def push_progress_entry(self, text):
        """git 배관으로 origin/main 위에 PROGRESS.md 한 건만 얹은 커밋을 만들어 push. (성공여부, 설명)"""
        root = self.quant_root()

        def git(*args, **kwargs):
            return subprocess.run(['git', '-C', str(root), *args], text=True, capture_output=True,
                                  timeout=kwargs.pop('timeout', 60), **kwargs)

        if git('fetch', 'origin', 'main', '--quiet').returncode != 0:
            return False, 'origin을 가져오지 못했습니다(네트워크/권한 확인).'
        base = git('rev-parse', 'origin/main').stdout.strip()
        if not base:
            return False, 'origin/main을 찾지 못했습니다.'
        current = git('show', f'{base}:PROGRESS.md')
        if current.returncode != 0:
            return False, 'PROGRESS.md를 읽지 못했습니다.'
        stamp = time.strftime('%Y-%m-%d %H:%M KST', time.localtime())
        updated = current.stdout.rstrip('\n') + f'\n\n### 메모 ({stamp}, 텔레그램)\n\n{text}\n'

        blob = subprocess.run(['git', '-C', str(root), 'hash-object', '-w', '--stdin'],
                              input=updated, text=True, capture_output=True, timeout=60)
        if blob.returncode != 0:
            return False, '내용을 저장소에 기록하지 못했습니다.'

        # 임시 인덱스를 써서 VM 워킹트리의 인덱스를 전혀 건드리지 않는다.
        index = self.state / f'progress-index-{os.getpid()}'
        env = {**os.environ, 'GIT_INDEX_FILE': str(index)}
        try:
            if subprocess.run(['git', '-C', str(root), 'read-tree', base], env=env,
                              capture_output=True, timeout=60).returncode != 0:
                return False, '트리를 준비하지 못했습니다.'
            if subprocess.run(['git', '-C', str(root), 'update-index', '--cacheinfo',
                               f'100644,{blob.stdout.strip()},PROGRESS.md'], env=env,
                              capture_output=True, timeout=60).returncode != 0:
                return False, '변경을 인덱스에 넣지 못했습니다.'
            tree = subprocess.run(['git', '-C', str(root), 'write-tree'], env=env,
                                  text=True, capture_output=True, timeout=60)
            if tree.returncode != 0:
                return False, '트리를 만들지 못했습니다.'
        finally:
            index.unlink(missing_ok=True)

        message = f'Add a PROGRESS note sent from Telegram ({stamp})'
        commit = subprocess.run(
            ['git', '-C', str(root), '-c', 'user.name=quant-telegram-bridge',
             '-c', 'user.email=quant-telegram-bridge@localhost', '-c', 'commit.gpgsign=false',
             'commit-tree', tree.stdout.strip(), '-p', base, '-m', message],
            text=True, capture_output=True, timeout=60)
        if commit.returncode != 0:
            return False, '커밋을 만들지 못했습니다.'
        new_sha = commit.stdout.strip()
        push = git('push', 'origin', f'{new_sha}:main', timeout=180)
        if push.returncode != 0:
            tail = (push.stderr.strip().splitlines() or ['push 실패'])[-1]
            return False, self.redact(tail[:160])
        return True, f'{base[:7]}..{new_sha[:7]}'

    # ---- 저장소 읽기 명령 (LLM을 부르지 않는다 — 폰에서 즉시, 할당량 0) -------------------------------
    # 배경: 예전에는 "PROGRESS 마지막 항목이 뭐였지?" 같은 확인 하나에도 수 분짜리 Claude 작업을 띄워야 했다.
    # docs/TELEGRAM_REPO_BRIDGE_SPEC.md 3-2 참고.

    CAT_MAX_LINES = 80  # 텔레그램 한 메시지에 무리 없이 들어가는 선
    CAT_MAX_CHARS = 3500
    LOG_MAX_COMMITS = 20

    def safe_repo_file(self, relpath):
        """저장소 안의 파일 경로로만 해석한다. 벗어나거나 없으면 (None, 사유)."""
        root = self.quant_root()
        if not relpath or relpath.startswith('/') or '\x00' in relpath:
            return None, '저장소 기준 상대경로를 주세요. 예: /cat PROGRESS.md'
        try:
            target = (root / relpath).resolve()
        except (OSError, RuntimeError):
            return None, '경로를 해석하지 못했습니다.'
        if root != target and root not in target.parents:
            return None, '저장소 밖의 경로는 읽을 수 없습니다.'
        if not target.is_file():
            return None, f'그런 파일이 없습니다: {relpath}'
        return target, None

    def cat_file(self, rest):
        """/cat <경로> [줄수] — 파일 끝부분을 보여준다."""
        parts = rest.split()
        if not parts:
            return '사용법: /cat <저장소 기준 경로> [줄수]  예: /cat PROGRESS.md 30'
        relpath = parts[0]
        lines_wanted = self.CAT_MAX_LINES
        if len(parts) > 1 and parts[1].isdigit():
            lines_wanted = max(1, min(int(parts[1]), self.CAT_MAX_LINES))
        target, problem = self.safe_repo_file(relpath)
        if problem:
            return problem
        try:
            raw = target.read_bytes()
        except OSError as exc:
            return f'읽지 못했습니다: {type(exc).__name__}'
        if b'\x00' in raw[:8000]:
            return f'{relpath}: 바이너리 파일이라 표시하지 않습니다 ({len(raw):,} bytes).'
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            return f'{relpath}: UTF-8로 읽을 수 없는 파일입니다.'
        all_lines = text.splitlines()
        shown = all_lines[-lines_wanted:]
        body = '\n'.join(shown)
        if len(body) > self.CAT_MAX_CHARS:
            body = body[-self.CAT_MAX_CHARS:]
            body = body.split('\n', 1)[-1]  # 잘린 첫 줄은 버린다
        head = f'{relpath} — 전체 {len(all_lines)}줄 중 마지막 {len(shown)}줄'
        return f'{head}\n\n{self.redact(body)}'

    def repo_log(self, rest):
        """/log [개수] — 최근 커밋 요약."""
        count = 5
        if rest.strip().isdigit():
            count = max(1, min(int(rest.strip()), self.LOG_MAX_COMMITS))
        root = self.quant_root()
        result = subprocess.run(['git', '-C', str(root), 'log', '--oneline', '--no-decorate', f'-{count}'],
                                text=True, capture_output=True, timeout=15)
        if result.returncode != 0:
            return f'git log 실패: {result.stderr.strip()[:200]}'
        return f'최근 커밋 {count}개\n\n' + (result.stdout.strip() or '(없음)')

    def repo_state(self):
        """/repo — VM 워킹트리의 git 상태 한눈에."""
        root = self.quant_root()

        def git(*args, timeout=20):
            done = subprocess.run(['git', '-C', str(root), *args], text=True, capture_output=True, timeout=timeout)
            return done.stdout.strip() if done.returncode == 0 else ''

        head = git('log', '--oneline', '--no-decorate', '-1') or '(알 수 없음)'
        subprocess.run(['git', '-C', str(root), 'fetch', 'origin', '--quiet'],
                       capture_output=True, timeout=60)
        behind = git('rev-list', '--count', 'HEAD..origin/main') or '?'
        ahead = git('rev-list', '--count', 'origin/main..HEAD') or '?'
        dirty = [line for line in git('status', '--porcelain', '--untracked-files=no').splitlines() if line]
        lines = [f'VM 저장소: {root}',
                 f'HEAD: {head}',
                 f'origin/main 대비: {behind}개 뒤, {ahead}개 앞']
        if dirty:
            lines.append(f'미커밋 수정 {len(dirty)}개:')
            lines += [f'  {item}' for item in dirty[:10]]
            if len(dirty) > 10:
                lines.append(f'  … 외 {len(dirty) - 10}개')
        else:
            lines.append('미커밋 수정: 없음')
        return '\n'.join(lines)

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

    def digest_summary(self, db):
        # A single "catch me up" command instead of scrolling every individual notification --
        # meant for someone who only opens Telegram in short, infrequent windows.
        last = db.execute("SELECT value FROM meta WHERE key='last_digest_at'").fetchone()
        since = float(last[0]) if last else 0
        now = time.time()
        db.execute("INSERT INTO meta VALUES('last_digest_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(now),))
        finished = db.execute("SELECT id,backend,project,status FROM jobs WHERE finished_at > ? ORDER BY id DESC LIMIT 20",
                              (since,)).fetchall()
        finished_total = db.execute('SELECT COUNT(*) FROM jobs WHERE finished_at > ?', (since,)).fetchone()[0]
        active = db.execute("SELECT id,backend,project,status FROM jobs WHERE status IN "
                            "('queued','retry','running','blocked') ORDER BY id").fetchall()
        lines = []
        if finished:
            lines.append(f'지난 확인 이후 끝난 작업 {finished_total}건:')
            lines.extend(f'  {r["id"]} [{r["backend"]}] {r["project"]} - {r["status"]}' for r in reversed(finished))
            if finished_total > len(finished):
                lines.append(f'  ...외 {finished_total - len(finished)}건 더 (/queue, /status 참고)')
        else:
            lines.append('지난 확인 이후 새로 끝난 작업 없음.')
        lines.append('')
        if active:
            lines.append(f'지금 대기/실행/차단 중 {len(active)}건:')
            lines.extend(f'  {r["id"]} [{r["backend"]}] {r["project"]} - {r["status"]}' for r in active)
        else:
            lines.append('지금 대기/실행 중인 작업 없음.')
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
            db.execute('UPDATE jobs SET status=?,summary=?,finished_at=? WHERE id=?', (status, summary, time.time(), uid))

    def available_memory_mb(self):
        try:
            with open('/proc/meminfo') as meminfo:
                for line in meminfo:
                    if line.startswith('MemAvailable:'):
                        return int(line.split()[1]) / 1024
        except (OSError, ValueError, IndexError):
            return None
        return None

    def has_capacity(self):
        # max_concurrent_jobs (worker thread count) is just an upper ceiling now -- this decides,
        # within that ceiling, whether the VM actually has room for one more concurrent job right
        # now, based on real load/memory rather than a fixed guess. Oracle's Always-Free tier is
        # small (2 OCPU/12GB on this instance) so headroom is genuinely scarce.
        with self.children_lock:
            running = len(self.children)
        if running == 0:
            # Never block the very first job -- a chronically "full" reading (e.g. from something
            # else on the box) must not stall the whole pipeline forever with nobody watching.
            return True
        try:
            load1 = os.getloadavg()[0]
        except OSError:
            load1 = 0.0
        cpu_count = os.cpu_count() or 1
        if load1 >= cpu_count * self.cfg.get('max_load_per_cpu', 1.5):
            return False
        available = self.available_memory_mb()
        if available is not None and available < self.cfg.get('min_free_memory_mb', 1024):
            return False
        return True

    def claim_job(self):
        # Claiming (select + mark 'running') must be atomic across worker threads so two
        # workers can never pick the same job, or two jobs from the same project at once.
        if not self.has_capacity():
            return None
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
        # max_concurrent_jobs is just the upper ceiling on thread count -- has_capacity() (in
        # claim_job) is what actually decides how many run at once, based on real CPU load and
        # free memory, so this can safely be set higher than the VM could ever really sustain.
        workers = [threading.Thread(target=self.worker_loop, daemon=True)
                   for _ in range(max(1, self.cfg.get('max_concurrent_jobs', 8)))]
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
