"""에이전트 야간 배치 (설계 S4·S5, docs/AGENTIC_QUANT_SYSTEM_DESIGN.md 4절) — 매일 03:00 KST.

루프: [결정론 정리] → [다음 작업 1개 계획] → [에이전트 1회 실행] → 반복. 계획은 매번 파일·DB 상태에서 새로 계산하므로
(별도 큐 없음) 중간에 끊겨도 다음 밤 같은 자리에서 이어진다. 한 밤에 같은 (역할, 대상)은 한 번만 돈다.

가설 한 건의 흐름(research/hypotheses/<id>/):
  Writer → spec.json → [등록: 스펙 검증] → Implementer → signal.py, test_signal.py → [결정론 검사: pytest + 스모크]
  → Critic → critic.json(현재 signal.py 해시에 대한 approve/reject) → [동결(주간 상한) → 즉시 심판]
  검사 실패·Critic 반려 → Implementer 재작업(가설당 최대 MAX_IMPL_ROUNDS) → 초과 시 abandoned.
Scout 는 매일 research/scout/<날짜>.md 에 씨앗을, Post-mortem 은 일요일 research/failures.md 에 실패 원인을 쓴다.

안전장치:
- 에이전트별 허용 도구를 좁히고(쓰기는 자기 작업 폴더만), 실행 후 research/ 밖 추적 파일 변경은 되돌린다(_guard).
- 자식 프로세스 환경에서 브로커·텔레그램 등 비밀값(KEY/SECRET/TOKEN/PASSWORD)을 뺀다(Claude 자격증명 제외).
- Critic 은 백테스트 결과를 볼 수 없다(심판은 Critic 승인 뒤에만 돈다). Writer 는 동결된 스펙을 바꿀 수 없다.
- 사용량 한도에 걸리면 그 밤 배치를 멈춘다(재시도 폭주 없음). 예산·시간 창은 core.agent_budget.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal as _signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from core import agent_budget as budget
from core import hypothesis_registry as reg
from core import hypothesis_spec as hs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESEARCH = PROJECT_ROOT / "research"
WS = RESEARCH / "hypotheses"
SCOUT_DIR = RESEARCH / "scout"
PROMPTS = RESEARCH / "agent_prompts"
FAILURES = RESEARCH / "failures.md"
CONTEXT = RESEARCH / "context.md"
MAX_IMPL_ROUNDS = 3
MAX_SPECS_PER_WRITER = 5
LIMIT_RE = re.compile(r"usage limit|rate.?limit|hit your limit|out of extra usage|\b429\b", re.I)
SECRET_ENV_RE = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD)", re.I)

AgentRunner = Callable[[str, str, list[str], budget.RoleConfig, float], dict]


# ---------------------------------------------------------------- 작업 폴더 상태
def _state(hid: str) -> dict:
    try:
        return json.loads((WS / hid / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(hid: str, st: dict) -> None:
    (WS / hid).mkdir(parents=True, exist_ok=True)
    (WS / hid / "state.json").write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _critic(hid: str) -> dict:
    try:
        return json.loads((WS / hid / "critic.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------- 결정론 검사
SMOKE = r"""
import json, sys, numpy as np, pandas as pd
sys.path.insert(0, sys.argv[1])
from core.hypothesis_engine import load_signal
spec = json.load(open(sys.argv[2]))
fn = load_signal(open(sys.argv[3]).read())
rng = np.random.default_rng(0); idx = pd.bdate_range("2021-01-01", periods=400)
prices = {}
for t in ["AAA", "BBB", "CCC"]:
    c = 100 * np.cumprod(1 + rng.normal(0.0004, 0.015, len(idx)))
    prices[t] = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e6}, index=idx)
for params in spec["signal"]["params_grid"]:
    out = fn({t: df.loc[:idx[-1]] for t, df in prices.items()}, idx[-1], dict(params))
    assert isinstance(out, dict), "score() 는 dict 를 돌려줘야 함"
    for k, v in out.items():
        assert isinstance(k, str) and isinstance(v, (int, float)), f"잘못된 항목 {k!r}: {v!r}"
print("smoke ok")
"""


def check_signal(hid: str, timeout: int = 180) -> tuple[bool, str]:
    d = WS / hid
    for cmd in ([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(d / "test_signal.py")],
                [sys.executable, "-c", SMOKE, str(PROJECT_ROOT), str(d / "spec.json"), str(d / "signal.py")]):
        try:
            p = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, f"시간 초과({timeout}s): {' '.join(cmd[:4])}"
        if p.returncode != 0:
            return False, (p.stdout + p.stderr)[-1500:]
    return True, "tests+smoke ok"


# ---------------------------------------------------------------- git 가드
def _porcelain() -> set[str]:
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=PROJECT_ROOT,
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line for line in out.splitlines() if line.strip()}


def _guard(before: set[str]) -> list[str]:
    """에이전트 실행 전에는 없던 research/ 밖 변경을 되돌린다. 되돌린 경로 목록."""
    reverted = []
    for line in _porcelain() - before:
        path = line[3:].strip().strip('"')
        if path.startswith("research/") and not path.startswith("research/agent_prompts/"):
            continue
        full = PROJECT_ROOT / path
        if line.startswith("??"):
            if full.is_file():
                full.unlink()
        else:
            subprocess.run(["git", "checkout", "--", path], cwd=PROJECT_ROOT, capture_output=True, timeout=30)
        reverted.append(path)
    return reverted


# ---------------------------------------------------------------- Claude 실행
def _child_env() -> dict:
    env = {k: v for k, v in os.environ.items()
           if not (SECRET_ENV_RE.search(k) and not k.startswith(("ANTHROPIC_", "CLAUDE_")))}
    env.pop("CLAUDECODE", None)
    if "CLAUDE_CONFIG_DIR" not in env and (PROJECT_ROOT / ".claude").is_dir():
        env["CLAUDE_CONFIG_DIR"] = str(PROJECT_ROOT / ".claude")
    return env


def system_prompt(role: str) -> str:
    return (PROMPTS / f"{role}.md").read_text(encoding="utf-8") + "\n\n---\n\n" + (PROMPTS / "_contract.md").read_text(encoding="utf-8")


def claude_runner(role: str, prompt: str, tools: list[str], cfg: budget.RoleConfig, timeout: float) -> dict:
    claude = os.environ.get("CLAUDE_BIN", "/usr/local/bin/claude")
    system = system_prompt(role)
    cmd = [claude, "-p", "--output-format", "json", "--no-session-persistence", "--model", cfg.model,
           "--max-turns", str(cfg.max_turns), "--allowedTools", ",".join(tools), "--append-system-prompt", system]
    started = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=PROJECT_ROOT, env=_child_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        out, err = proc.communicate(prompt, timeout=max(timeout, 1))
        timed_out = False
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, _signal.SIGTERM)
        out, err = proc.communicate()
        timed_out = True
    res = {"ok": False, "limited": bool(LIMIT_RE.search((out or "") + (err or ""))), "timed_out": timed_out,
           "duration_s": round(time.monotonic() - started, 1), "cost_usd": None, "turns": None, "summary": ""}
    try:
        data = json.loads(out)
        res.update(ok=not data.get("is_error") and data.get("subtype") == "success" and not timed_out,
                   cost_usd=data.get("total_cost_usd"), turns=data.get("num_turns"),
                   summary=str(data.get("result") or "")[:500])
    except (ValueError, TypeError):
        res["summary"] = (err or out or "")[-500:]
    return res


# ---------------------------------------------------------------- 도구·프롬프트
def tools_for(role: str, hid: str = "") -> list[str]:
    ro = ["Read", "Glob", "Grep"]
    if role == "scout":
        return ro + ["WebSearch", "WebFetch", "Write(research/scout/**)", "Edit(research/scout/**)"]
    if role == "writer":
        return ro + ["Write(research/hypotheses/**)", "Edit(research/hypotheses/**)"]
    if role == "implementer":
        return ro + [f"Write(research/hypotheses/{hid}/**)", f"Edit(research/hypotheses/{hid}/**)",
                     f"Bash(python -m pytest research/hypotheses/{hid}:*)"]
    if role == "critic":
        return ro + [f"Write(research/hypotheses/{hid}/critic.json)", f"Edit(research/hypotheses/{hid}/critic.json)"]
    if role == "postmortem":
        return ro + ["Write(research/failures.md)", "Edit(research/failures.md)"]
    raise ValueError(role)


def _new_ids(n: int, now: datetime) -> list[str]:
    day = budget.kst(now).strftime("%Y%m%d")
    taken = {p.name for p in WS.glob(f"H-{day}-*")} | {h["id"] for h in reg.list_by_status()}
    out, i = [], 1
    while len(out) < n and i < 1000:
        hid = f"H-{day}-{i:03d}"
        if hid not in taken:
            out.append(hid)
        i += 1
    return out


def write_context(now: datetime) -> None:
    RESEARCH.mkdir(parents=True, exist_ok=True)
    f = reg.funnel(now=now.replace(tzinfo=None))
    lines = [f"# 연구 현황 ({budget.kst(now):%Y-%m-%d %H:%M} KST, 배치가 자동 생성)", "",
             f"- 누적 시도 수 N = {f['cumulative_trials']} (다중검정 기준이 N 에 따라 엄격해짐)",
             f"- 이번 주 동결 {f['frozen_this_week']}/{f['weekly_freeze_cap']}, 상태별 {f['counts']}", "",
             "| id | 상태 | 가설 | 심판 사유 |", "|---|---|---|---|"]
    for h in reg.list_by_status():
        reasons = "; ".join((h.get("judge") or {}).get("reasons") or [])[:160]
        lines.append(f"| {h['id']} | {h['status']} | {h['spec']['thesis'][:80]} | {reasons} |")
    CONTEXT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def prompt_for(role: str, hid: str, now: datetime, extra: dict) -> str:
    today = budget.kst(now).strftime("%Y-%m-%d")
    if role == "scout":
        return (f"오늘은 {today}. research/context.md(현재 가설·실패)와 research/failures.md 를 읽고, 무료로 얻을 수 있는 "
                f"일봉 데이터로 검증 가능한 새 전략 가설 씨앗 3~6개를 research/scout/{today}.md 에 써라.")
    if role == "writer":
        ids = ", ".join(extra["ids"])
        return (f"오늘은 {today}. 최근 research/scout/*.md, research/context.md, research/failures.md 를 읽고 가설 스펙을 "
                f"최대 {len(extra['ids'])}개 작성하라. 반드시 이 id 만 쓴다: {ids}. 각 스펙은 "
                f"research/hypotheses/<id>/spec.json 에 저장한다(다른 파일은 쓰지 않는다).")
    if role == "implementer":
        fb = extra.get("feedback") or "없음(첫 구현)"
        return (f"가설 {hid}: research/hypotheses/{hid}/spec.json 을 구현하라. 같은 폴더에 signal.py(score 함수)와 "
                f"test_signal.py 를 쓰고 `python -m pytest research/hypotheses/{hid}` 로 확인하라.\n이전 피드백:\n{fb}")
    if role == "critic":
        return (f"가설 {hid}: research/hypotheses/{hid}/spec.json, signal.py, test_signal.py 를 검토하고 "
                f"research/hypotheses/{hid}/critic.json 에 판정을 써라.")
    if role == "postmortem":
        return (f"오늘은 {today}. research/postmortem_input.md(지난 주 실패 가설과 사유)를 읽고 research/failures.md 에 "
                f"재발 방지 교훈을 추가하라.")
    raise ValueError(role)


# ---------------------------------------------------------------- 결정론 정리
def _dead_end(st: dict, cur: Optional[str], crit: dict) -> bool:
    """재작업 한도를 다 쓴 뒤에도 남은 단계가 실패로 끝났는가(검토 대기 중이면 아직 아니다)."""
    if cur is None:
        return True
    if st.get("tested_hash") == cur and not st.get("test_ok"):
        return True
    return st.get("critic_hash") == cur and crit.get("verdict") != "approve"


def housekeeping(now: datetime, judged: set[str], log: list[str], judge_fn=None) -> None:
    from core import hypothesis_judge as hj

    judge_fn = judge_fn or hj.judge_frozen
    known = {h["id"]: h for h in reg.list_by_status()}
    for spec_path in sorted(WS.glob("H-*/spec.json")):
        hid = spec_path.parent.name
        if hid in known or _state(hid).get("invalid"):
            continue
        try:
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            if spec.get("id") != hid:
                raise hs.SpecError(f"id 불일치({spec.get('id')} ≠ 폴더 {hid})")
            reg.register_draft(spec)
            log.append(f"등록 {hid}")
        except (ValueError, hs.SpecError) as exc:
            _save_state(hid, {**_state(hid), "invalid": str(exc)[:1000]})
            log.append(f"스펙 거부 {hid}: {str(exc)[:120]}")
    for h in reg.list_by_status(reg.DRAFT):
        hid, st = h["id"], _state(h["id"])
        sig = WS / hid / "signal.py"
        cur = _sha(sig)
        crit = _critic(hid)
        if cur and st.get("critic_hash") == cur and crit.get("verdict") == "approve" and st.get("tested_hash") == cur and st.get("test_ok"):
            try:
                reg.freeze(hid, sig.read_text(encoding="utf-8"))
                log.append(f"동결 {hid}")
            except reg.CapReached as exc:
                log.append(f"동결 보류 {hid}: {exc}")
                continue
        elif st.get("impl_rounds", 0) >= MAX_IMPL_ROUNDS and _dead_end(st, cur, crit):
            reg.transition(hid, reg.ABANDONED, f"구현 {MAX_IMPL_ROUNDS}회 내 검사/Critic 통과 실패")
            log.append(f"폐기 {hid}")
    for h in reg.list_by_status(reg.FROZEN):
        if h["id"] in judged:
            continue
        judged.add(h["id"])
        out = judge_fn(h["id"])
        log.append(f"심판 {h['id']}: {out.get('status')}" + (f" ({'; '.join(out['judge']['reasons'])[:150]})"
                                                               if out.get("judge") and out["judge"]["reasons"] else ""))


# ---------------------------------------------------------------- 계획
def plan(now: datetime, done: set[tuple[str, str]]) -> Optional[tuple[str, str, dict]]:
    def ok(role: str, key: str = "") -> bool:
        return (role, key) not in done and budget.can_launch(role, now)[0]

    if ok("scout"):
        return "scout", "", {}
    for h in reg.list_by_status(reg.DRAFT):
        hid, st = h["id"], _state(h["id"])
        if st.get("impl_rounds", 0) >= MAX_IMPL_ROUNDS and not (WS / hid / "signal.py").exists():
            continue
        cur = _sha(WS / hid / "signal.py")
        if cur is None:
            if ok("implementer", hid):
                return "implementer", hid, {"feedback": None}
            continue
        if st.get("tested_hash") != cur:
            passed, msg = check_signal(hid)
            st.update(tested_hash=cur, test_ok=passed, test_msg=msg)
            _save_state(hid, st)
        if not st.get("test_ok"):
            if st.get("impl_rounds", 0) < MAX_IMPL_ROUNDS and ok("implementer", hid):
                return "implementer", hid, {"feedback": f"결정론 검사 실패:\n{st.get('test_msg')}"}
            continue
        crit = _critic(hid)
        if st.get("critic_hash") != cur:
            if ok("critic", hid):
                return "critic", hid, {"hash": cur}
            continue
        if crit.get("verdict") != "approve" and st.get("impl_rounds", 0) < MAX_IMPL_ROUNDS and ok("implementer", hid):
            return "implementer", hid, {"feedback": "Critic 반려:\n" + json.dumps(crit.get("issues", []), ensure_ascii=False)[:1500]}
    f = reg.funnel(now=now.astimezone(timezone.utc).replace(tzinfo=None))
    room = f["weekly_freeze_cap"] - f["frozen_this_week"] - f["counts"].get(reg.DRAFT, 0)
    if room > 0 and ok("writer"):
        return "writer", "", {"ids": _new_ids(min(room, MAX_SPECS_PER_WRITER), now)}
    if ok("postmortem"):
        return "postmortem", "", {}
    return None


def _postmortem_input(now: datetime) -> None:
    cutoff = now.astimezone(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    rows = [h for h in reg.list_by_status(reg.FAIL, reg.RETIRED, reg.ABANDONED) if h["updated_at"] >= cutoff]
    lines = ["# 지난 7일 실패 가설 (배치 자동 생성)", ""]
    for h in rows:
        j = h.get("judge") or {}
        lines.append(f"## {h['id']} ({h['status']})\n- 가설: {h['spec']['thesis']}\n- 사유: {'; '.join(j.get('reasons') or []) or '—'}\n")
    (RESEARCH / "postmortem_input.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------- 실행
def run_batch(*, now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
              runner: Optional[AgentRunner] = None, notify: Optional[Callable[[str], Any]] = None,
              judge_fn=None, max_tasks: int = 40) -> dict:
    runner = runner or claude_runner
    WS.mkdir(parents=True, exist_ok=True)
    SCOUT_DIR.mkdir(parents=True, exist_ok=True)
    done: set[tuple[str, str]] = set()
    judged: set[str] = set()
    log: list[str] = []
    ran: list[dict] = []
    stop_reason = "no more tasks"
    for _ in range(max_tasks):
        now = now_fn()
        housekeeping(now, judged, log, judge_fn)
        if budget.seconds_until_hard_stop(now) <= 60:
            stop_reason = "hard stop time"
            break
        task = plan(now, done)
        if task is None:
            break
        role, hid, extra = task
        done.add((role, hid))
        cfg = budget.effective(role)  # 사람이 허브/텔레그램에서 고른 모델 반영
        if role in ("scout", "writer"):
            write_context(now)
        if role == "postmortem":
            _postmortem_input(now)
        before = _porcelain()
        res = runner(role, prompt_for(role, hid, now, extra), tools_for(role, hid), cfg,
                     min(cfg.timeout_sec, budget.seconds_until_hard_stop(now)))
        reverted = _guard(before)
        if role == "implementer":
            st = _state(hid)
            st["impl_rounds"] = st.get("impl_rounds", 0) + 1
            _save_state(hid, st)
        if role == "critic":
            st = _state(hid)
            st["critic_hash"] = extra["hash"] if _sha(WS / hid / "signal.py") == extra["hash"] else None
            _save_state(hid, st)
        entry = {"at": budget.kst(now).isoformat(), "role": role, "target": hid, "model": cfg.model,
                 "ok": res.get("ok"), "limited": res.get("limited"), "timed_out": res.get("timed_out"),
                 "cost_usd": res.get("cost_usd"), "turns": res.get("turns"), "duration_s": res.get("duration_s"),
                 "reverted": reverted}
        budget.record(entry)
        ran.append(entry)
        if reverted:
            log.append(f"경고: {role} {hid} 가 허용 범위 밖 파일을 바꿔 되돌림: {reverted[:5]}")
        if res.get("limited"):
            stop_reason = "usage limit"
            break
    housekeeping(now_fn(), judged, log, judge_fn)
    result = {"ran": ran, "log": log, "stop_reason": stop_reason, "budget": budget.summary(now_fn())}
    if notify and (ran or log):
        notify(format_summary(result))
    return result


def format_summary(res: dict) -> str:
    b = res["budget"]
    roles = {}
    for r in res["ran"]:
        roles[r["role"]] = roles.get(r["role"], 0) + 1
    lines = [f"[에이전트 배치] 실행 {len(res['ran'])}건 {roles} · 종료: {res['stop_reason']}",
             f"예산: 오늘 ${b['night_cost']:.2f}/{b['nightly_cap']:.0f}, 이번 주 ${b['week_cost']:.2f}/{b['weekly_cap']:.0f}"]
    lines += [f"- {x}" for x in res["log"][:15]]
    return "\n".join(lines)
