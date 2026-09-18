#!/usr/bin/env python3
"""Persistent, paper-only supervisor for the pre-registered Quant experiment.

The supervisor owns operational state outside git, launches at most one Codex
turn at a time, and sends a self-contained HTML report to the existing private
Telegram chat every 24 hours.  It deliberately does not know brokerage keys or
place orders.
"""
import argparse
import html
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import urllib.request
import uuid


LIMIT = re.compile(r"usage_limit_(?:reached|exceeded)|usage limit|rate_limit_exceeded|rate limit|too many requests|\b429\b", re.I)
DAY_COMPLETE = re.compile(r"\bDAY[_ -]?(\d{1,2})[_ -]?COMPLETE\b", re.I)


class ExperimentSupervisor:
    def __init__(self, root, dry_run=False):
        self.root = Path(root).resolve()
        self.dry_run = dry_run
        self.control_dir = self.root / '.experiment-control'
        self.control_path = self.control_dir / 'control.json'
        self.state_path = self.control_dir / 'state.json'
        self.report_dir = self.control_dir / 'reports'
        self.log_dir = self.root / 'data' / 'cache' / 'experiment_supervisor_logs'
        self.env = self.read_env(Path(os.environ.get(
            'TELEGRAM_EXPERIMENT_ENV_FILE',
            self.root / '.codex-telegram-runtime' / 'telegram.env')))
        self.interval = int(os.environ.get('EXPERIMENT_AGENT_INTERVAL_SECONDS', '14400'))
        self.timeout = int(os.environ.get('EXPERIMENT_AGENT_TIMEOUT_SECONDS', '10800'))
        self.report_interval = int(os.environ.get('EXPERIMENT_REPORT_INTERVAL_SECONDS', '86400'))
        self.codex = Path(os.environ.get(
            'CODEX_BIN', self.root / '.codex-telegram-runtime' / 'node_modules' / '.bin' / 'codex'))
        self.stop = False
        self.child = None

    @staticmethod
    def read_env(path):
        values = {}
        try:
            for raw in path.read_text().splitlines():
                key, separator, value = raw.strip().removeprefix('export ').partition('=')
                if separator and key and not key.startswith('#'):
                    values[key.strip()] = value.strip().strip('"\'')
        except OSError:
            pass
        return values

    @staticmethod
    def load_json(path, default):
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return default

    @staticmethod
    def write_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        candidate = path.with_suffix(path.suffix + '.tmp')
        candidate.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        candidate.replace(path)

    def state(self):
        now = time.time()
        state = self.load_json(self.state_path, {})
        state.setdefault('started_at', now)
        state.setdefault('phase', 'validation')
        state.setdefault('completed_days', 0)
        state.setdefault('next_agent_at', now)
        state.setdefault('last_report_at', 0)
        state.setdefault('total_agent_runs', 0)
        return state

    def control(self):
        return self.load_json(self.control_path, {'mode': 'running'})

    def save(self, state):
        self.write_json(self.state_path, state)

    def git(self, *args):
        try:
            result = subprocess.run(['git', '-C', str(self.root), *args], text=True,
                                    capture_output=True, timeout=20)
            return result.stdout.strip() if result.returncode == 0 else ''
        except (OSError, subprocess.TimeoutExpired):
            return ''

    def completed_days(self):
        progress = self.root / 'docs' / 'experiment_validation' / 'PROGRESS.md'
        try:
            completed = {int(match.group(1)) for match in DAY_COMPLETE.finditer(progress.read_text())
                         if 1 <= int(match.group(1)) <= 14}
        except OSError:
            completed = set()
        return len(completed), sorted(completed)

    def activity_prompt(self, state):
        completed_count, completed = self.completed_days()
        final = self.root / 'docs' / 'experiment_validation' / 'FINAL_VALIDATION.md'
        if final.exists() or completed_count == 14:
            phase = 'extension'
            task = (
                '기본 14일 검증이 완료된 것으로 보인다. FINAL_VALIDATION.md와 모든 근거를 먼저 검토한다. '
                '이전에 검증하지 않은 가설을 정확히 하나만 선택하여, 문헌 근거·경제적 직관·사전등록 규칙·'
                '실패 조건을 docs/experiment_validation/hypotheses/에 기록한 뒤 그 가설의 첫 검증 단계만 수행한다. '
                '새 가설은 기존 후보 여섯 개의 파라미터 미세조정이어서는 안 된다.')
        else:
            phase = 'validation'
            next_day = next(day for day in range(1, 15) if day not in completed)
            task = (
                f'고정된 14일 프로토콜의 아직 완료되지 않은 Day {next_day}만 수행한다. '
                '출력은 docs/experiment_validation/ 아래에 저장하고, 끝에 PROGRESS.md에 '
                f'`DAY_{next_day}_COMPLETE`와 생성 파일·데이터 해시·검증 결과를 기록한다. '
                '이 표식은 해당 Day의 모든 통과 조건을 충족했을 때만 기록한다.')
        state['phase'] = phase
        state['completed_days'] = completed_count
        return task

    def prompt(self, state):
        task = self.activity_prompt(state)
        return f'''당신은 Quant의 지속적 실험 감독 Codex다. 작업 루트는 {self.root}다.

먼저 docs/TWO_WEEK_STRATEGY_VALIDATION_PROTOCOL.md, PROGRESS.md(있으면), git status/log,
그리고 .experiment-control/state.json을 읽어라. 이 작업은 연구·백테스트·문서화만 허용한다.
실계좌 주문, 브로커 인증정보 변경, .env 출력 또는 커밋, 기존 서비스 중지/재시작/삭제, force push는 금지다.
사전등록된 6개 후보·기준선·선택 게이트는 변경하지 마라. 데이터 누수와 같은 날 종가 체결을 특히 점검하라.
기존의 uncommitted 작업을 덮어쓰지 말고, 충돌이나 모호함은 RESUME_NOTE.md에 정확히 남겨라.
유의미한 코드·문서 변경은 관련 테스트 후 git 관례를 확인해 commit/push하되, 자동 생성 일일 HTML 보고서는 커밋하지 마라.
작업을 완료할 수 없거나 한도/오류로 중단되면 RESUME_NOTE.md에 다음 단계와 명령을 남겨라.

이번 감독 차례의 단 하나의 목표:
{task}

최종 답변에는 수행한 일, 검증 결과, 다음 자동 감독이 해야 할 일을 짧게 적어라.'''

    def launch_agent(self, state):
        if not self.codex.exists():
            state['last_error'] = f'Codex CLI가 없습니다: {self.codex}'
            state['next_agent_at'] = time.time() + 3600
            self.save(state)
            return
        task = self.activity_prompt(state)
        log_path = self.log_dir / f"codex_{time.strftime('%Y%m%d_%H%M%S', time.gmtime())}.jsonl"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        instructions = self.prompt(state)
        cmd = ['/usr/bin/flock', '-n', str(self.control_dir / 'agent.lock'), str(self.codex),
               '-a', 'never', 'exec', '--ephemeral', '--json', '--color', 'never',
               '-s', 'danger-full-access', '-C', str(self.root),
               '-c', 'model_reasoning_effort="xhigh"',
               '-c', 'sandbox_workspace_write.network_access=true', '-']
        env = os.environ.copy()
        env['CODEX_HOME'] = str(self.root / '.codex-telegram-runtime' / 'auth')
        try:
            with log_path.open('w') as output:
                child = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=output,
                                         stderr=subprocess.STDOUT, text=True, cwd=self.root,
                                         env=env, start_new_session=True)
                child.stdin.write(instructions)
                child.stdin.close()
        except OSError as exc:
            state['last_error'] = f'Codex 시작 실패: {exc}'
            state['next_agent_at'] = time.time() + 3600
            self.save(state)
            return
        now = time.time()
        self.child = child
        state.update({'agent_pid': child.pid, 'agent_started_at': now, 'last_agent_at': now,
                      'current_activity': task, 'last_log_path': str(log_path),
                      'total_agent_runs': state.get('total_agent_runs', 0) + 1,
                      'last_error': ''})
        self.save(state)

    def agent_finished(self, state):
        pid = state.get('agent_pid')
        if not isinstance(pid, int):
            return False
        if self.child is not None and self.child.pid == pid:
            if self.child.poll() is None:
                return False
            self.child = None
        try:
            os.kill(pid, 0)
            return False
        except ProcessLookupError:
            pass
        log_path = Path(state.get('last_log_path', ''))
        try:
            tail = log_path.read_text(errors='replace')[-12000:]
        except OSError:
            tail = ''
        state.pop('agent_pid', None)
        state.pop('agent_started_at', None)
        state['current_activity'] = '다음 감독 실행 대기'
        if LIMIT.search(tail):
            note = self.root / 'RESUME_NOTE.md'
            if not note.exists():
                note.write_text('# Experiment supervisor resume note\nCodex usage limit 또는 rate limit으로 중단됨. '
                                'docs/TWO_WEEK_STRATEGY_VALIDATION_PROTOCOL.md와 PROGRESS.md를 읽고 마지막 미완료 단계부터 재개하세요.\n')
            state['last_error'] = 'Codex 사용량/요청 한도 감지: 15분 뒤 재개'
            state['next_agent_at'] = time.time() + 900
        else:
            state['next_agent_at'] = time.time() + self.interval
        self.save(state)
        return True

    def stop_timeout(self, state):
        started = state.get('agent_started_at', 0)
        pid = state.get('agent_pid')
        if isinstance(pid, int) and started and time.time() - started > self.timeout:
            try:
                os.killpg(pid, signal.SIGTERM)
                state['last_error'] = f'Codex 감독 시간 제한({self.timeout // 60}분) 도달: 중지 후 재개 예정'
                self.save(state)
            except ProcessLookupError:
                pass

    def report_html(self, state):
        completed_count, completed = self.completed_days()
        head = self.git('rev-parse', '--short', 'HEAD') or 'unknown'
        changes = self.git('status', '--short').splitlines()
        now = time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())
        rows = ''.join(f'<li>Day {day}: 완료</li>' for day in completed) or '<li>아직 완료 표식 없음</li>'
        error = html.escape(str(state.get('last_error', '없음')))
        activity = html.escape(str(state.get('current_activity', '대기')))
        phase = html.escape(str(state.get('phase', 'validation')))
        return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>Quant experiment report</title>
<style>body{{font-family:system-ui,sans-serif;max-width:760px;margin:2rem auto;line-height:1.55}}code{{background:#f3f4f6;padding:.1rem .25rem}}.ok{{color:#176b3a}}.warn{{color:#9a4d00}}</style></head><body>
<h1>Quant 2주 전략 검증 보고</h1><p>생성: <code>{now}</code></p>
<h2>상태</h2><ul><li>단계: <b>{phase}</b></li><li>완료: <b>{completed_count}/14</b></li><li>현재: {activity}</li><li>Git HEAD: <code>{html.escape(head)}</code></li><li>작업 트리 변경: {len(changes)}개</li><li>최근 오류: <span class="warn">{error}</span></li></ul>
<h2>완료한 프로토콜 단계</h2><ul>{rows}</ul>
<h2>판정 원칙</h2><p>사전등록된 비용·표본외·PBO·Deflated Sharpe 게이트를 통과한 후보만 최소 한 달 paper trading으로 이동한다. 이 보고서는 실계좌 주문을 의미하지 않는다.</p>
<h2>다음 확인</h2><p>Telegram에서 <code>/experiment</code>로 즉시 상태를 확인하고, <code>/experiment pause</code>, <code>/experiment resume</code>, <code>/experiment stop</code>으로 제어할 수 있다.</p>
</body></html>'''

    def telegram_document(self, report, caption):
        token = self.env.get('TELEGRAM_BOT_TOKEN', '')
        chat_id = self.env.get('TELEGRAM_CHAT_ID', '')
        if not token or not chat_id:
            raise RuntimeError('Telegram token/chat id가 설정되지 않았습니다.')
        boundary = '----QuantExperiment' + uuid.uuid4().hex
        parts = []
        for name, value in {'chat_id': chat_id, 'caption': caption[:900]}.items():
            parts.extend([f'--{boundary}\r\n'.encode(),
                          f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                          str(value).encode(), b'\r\n'])
        parts.extend([f'--{boundary}\r\n'.encode(),
                      b'Content-Disposition: form-data; name="document"; filename="quant-experiment-report.html"\r\n',
                      b'Content-Type: text/html; charset=utf-8\r\n\r\n', report.read_bytes(), b'\r\n',
                      f'--{boundary}--\r\n'.encode()])
        request = urllib.request.Request(f'https://api.telegram.org/bot{token}/sendDocument', data=b''.join(parts),
                                         headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
        with urllib.request.urlopen(request, timeout=40) as response:
            result = json.load(response)
        if not result.get('ok'):
            raise RuntimeError('Telegram HTML 보고서 전송 거부')

    def send_report(self, state):
        self.report_dir.mkdir(parents=True, exist_ok=True)
        report = self.report_dir / f"quant_experiment_{time.strftime('%Y%m%d_%H%M%S', time.gmtime())}.html"
        report.write_text(self.report_html(state))
        if not self.dry_run:
            self.telegram_document(report, f"Quant 2주 실험 일일 보고: {state.get('completed_days', 0)}/14 완료, {state.get('phase', 'validation')}")
        state['last_report_at'] = time.time()
        state['last_report_path'] = str(report)
        self.save(state)

    def tick(self, report_only=False):
        if not self.control_path.exists():
            self.write_json(self.control_path, {'mode': 'running', 'created_at': time.time()})
        state = self.state()
        count, _ = self.completed_days()
        state['completed_days'] = count
        self.stop_timeout(state)
        self.agent_finished(state)
        now = time.time()
        if report_only or now - state.get('last_report_at', 0) >= self.report_interval:
            try:
                self.send_report(state)
            except Exception as exc:
                state['last_error'] = f'보고서 전송 실패: {exc}'
                self.save(state)
        if report_only or self.dry_run:
            return
        control = self.control()
        if control.get('mode', 'running') != 'running':
            state['current_activity'] = f"{control.get('mode')} 상태로 감독 실행 대기"
            self.save(state)
            return
        if not state.get('agent_pid') and now >= state.get('next_agent_at', now):
            self.launch_agent(state)

    def run(self):
        def shutdown(*_):
            self.stop = True
        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        while not self.stop:
            self.tick()
            for _ in range(60):
                if self.stop:
                    break
                time.sleep(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='/opt/quant')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--once-report', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    service = ExperimentSupervisor(args.root, args.dry_run)
    if args.once_report:
        service.tick(report_only=True)
    elif args.dry_run:
        service.tick()
    else:
        service.run()


if __name__ == '__main__':
    main()
