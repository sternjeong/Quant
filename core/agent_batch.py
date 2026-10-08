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
SAT_WS = RESEARCH / "satellite_lab" / "variants"  # 새틀라이트 R&D 아이디어 작업 폴더
SAT_MAX_ROUNDS = 3       # 아이디어 하나당 설계(재작업 포함) 최대 횟수
SAT_MAX_IN_FLIGHT = 2    # 동결 전 진행 중인 아이디어 수 상한
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


DEAD_END_ROLES = ("scout", "writer", "sat_designer")  # 새 방향을 고르는 역할만 실패 목록을 받는다


def system_prompt(role: str) -> str:
    if role in ("geo_analyst", "core_designer"):  # 가설 계약과 무관한 역할 — 자기 지시문만(+실패 방향 목록)
        parts = [(PROMPTS / f"{role}.md").read_text(encoding="utf-8")]
        if role == "core_designer" and (PROMPTS / "dead_ends.md").is_file():
            parts.append((PROMPTS / "dead_ends.md").read_text(encoding="utf-8"))
        return "\n\n---\n\n".join(parts)
    contract = "_sat_contract.md" if role.startswith("sat_") else "_contract.md"
    parts = [(PROMPTS / f"{role}.md").read_text(encoding="utf-8"), (PROMPTS / contract).read_text(encoding="utf-8")]
    if role in DEAD_END_ROLES and (PROMPTS / "dead_ends.md").is_file():
        parts.append((PROMPTS / "dead_ends.md").read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(parts)


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
    if role == "sat_designer":
        return ro + [f"Write(research/satellite_lab/variants/{hid}/**)", f"Edit(research/satellite_lab/variants/{hid}/**)",
                     f"Bash(python -m pytest research/satellite_lab/variants/{hid}:*)"]
    if role == "sat_critic":
        return ro + [f"Write(research/satellite_lab/variants/{hid}/critic.json)",
                     f"Edit(research/satellite_lab/variants/{hid}/critic.json)"]
    if role == "geo_analyst":
        return ["Read", "WebSearch", "WebFetch", f"Write(research/geo_shadow/{hid}.json)", f"Edit(research/geo_shadow/{hid}.json)"]
    if role == "core_designer":
        return ro + ["WebSearch", f"Write(research/core_lab/ideas/{hid}/**)", f"Edit(research/core_lab/ideas/{hid}/**)"]
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
        return (f"오늘은 {today}. research/context.md(현재 가설·실패), research/failures.md, research/factor_decay.md"
                f"(고전 팩터 공개 전후 감쇠)를 읽고, 무료로 얻을 수 있는 "
                f"일봉 데이터로 검증 가능한 새 전략 가설 씨앗 3~6개를 research/scout/{today}.md 에 써라.")
    if role == "writer":
        ids = ", ".join(extra["ids"])
        return (f"오늘은 {today}. 최근 research/scout/*.md, research/context.md, research/failures.md, "
                f"research/factor_decay.md 를 읽고 가설 스펙을 "
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
    if role == "sat_designer":
        fb = extra.get("feedback")
        if fb:
            return (f"새틀라이트 아이디어 {hid}: research/satellite_lab/variants/{hid}/ 의 파일을 고쳐라(id 유지). "
                    f"`python -m pytest research/satellite_lab/variants/{hid}` 로 확인하라.\n피드백:\n{fb}")
        topic = extra.get("topic", "selection")
        focus = {"selection": "어떤 종목을 고를지(신호·후보 풀·종목 수)를 바꾸는 아이디어. entry 는 close, exit 는 none 이나 trailing_stop 그대로 둬도 된다.",
                 "entry": "뽑힌 종목을 '언제 살지'(entry: delay 또는 pullback)를 바꾸는 아이디어. 종목 선정 신호는 현 규칙(S-SEED-000)을 그대로 쓴다.",
                 "exit": "'언제 팔지'(exit: take_profit·time_stop·trend_break·trailing_stop, 또는 보유기간)를 바꾸는 아이디어. 종목 선정 신호는 현 규칙을 그대로 쓴다.",
                 "guru": "거장 13F 보유(spec data: [\"guru13f\"], ctx.guru(종목))를 종목 선정에 쓰는 아이디어 — 보유·확신(상위 5)·신규 매수·여러 거장 합의 등. 시작 목록 S-SEED-018~025 와 겹치지 않게."}[topic]
        return (f"오늘은 {today}. research/satellite_lab/context.md 와 seeds/ 를 읽고 새 새틀라이트 아이디어 하나를 "
                f"research/satellite_lab/variants/{hid}/ 에 spec.json(id={hid}, topic=\"{topic}\"), signal.py, test_signal.py 로 만들어라. "
                f"이번 주제: {focus}")
    if role == "sat_critic":
        return (f"새틀라이트 아이디어 {hid}: research/satellite_lab/variants/{hid}/ 의 spec.json, signal.py, test_signal.py 를 "
                f"검토하고 research/satellite_lab/variants/{hid}/critic.json 에 판정을 써라.")
    if role == "core_designer":
        fb = extra.get("feedback")
        return (f"오늘은 {today}. {hid} 분기 코어 아이디어를 최대 3개, research/core_lab/ideas/{hid}/Q-{hid}-01.json ~ -03.json 으로 써라. "
                f"먼저 research/core_lab/context.md 와 research/results/ 의 코어 연구 보고서를 읽고 이미 탈락한 방향은 피한다."
                + (f"\n{fb}" if fb else ""))
    if role == "geo_analyst":
        from core.champion_strategy import CORE_UNIVERSE

        return (f"오늘은 {today}. {hid} 첫 거래일 코어 리밸런싱 전 국제정세 의견을 research/geo_shadow/{hid}.json 에 써라. "
                f"대상 {len(CORE_UNIVERSE)}자산: {', '.join(CORE_UNIVERSE)}. month 필드는 \"{hid}\".")
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
    # 국제정세 의견(월 1회)과 새틀라이트 R&D 를 새 일반 가설 작성(Writer)보다 먼저 — 하룻밤 예산이 앞 작업에 다 쓰여
    # 새틀라이트 차례가 오지 않는 일을 막는다(2026-10-02 사용자 우선순위).
    geo = geo_plan(now, done)
    if geo is not None:
        return geo
    core_task = core_plan(now, done)
    if core_task is not None:
        return core_task
    sat = sat_plan(now, done)
    if sat is not None:
        return sat
    f = reg.funnel(now=now.astimezone(timezone.utc).replace(tzinfo=None))
    room = f["weekly_freeze_cap"] - f["frozen_this_week"] - f["counts"].get(reg.DRAFT, 0)
    if room > 0 and ok("writer"):
        return "writer", "", {"ids": _new_ids(min(room, MAX_SPECS_PER_WRITER), now)}
    if ok("postmortem"):
        return "postmortem", "", {}
    return None


# ---------------------------------------------------------------- 새틀라이트 R&D 트랙 (2026-10-02)
# 아이디어 하나: sat_designer → spec.json·signal.py·test_signal.py → [결정론 검사: pytest + 합성 데이터 실행·미래 비의존]
# → sat_critic → critic.json → 배치가 data/satellite_lab/agent/<id>.json 에 ready_hash 기록(에이전트는 그 폴더에 못 쓴다)
# → VM 연구 창의 계산기(scripts/satellite_lab_worker.py)가 동결·심판. 실패·반려 → 같은 id 재작업, SAT_MAX_ROUNDS 넘으면 폐기.
SAT_SMOKE = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from core import satellite_lab as sl
d = sys.argv[2]
print(sl.smoke_check(json.load(open(d + "/spec.json")), open(d + "/signal.py").read()))
"""


def sat_check(sid: str, timeout: int = 300) -> tuple[bool, str]:
    d = SAT_WS / sid
    if not (d / "test_signal.py").exists():
        return False, "test_signal.py 없음"
    for cmd in ([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(d / "test_signal.py")],
                [sys.executable, "-c", SAT_SMOKE, str(PROJECT_ROOT), str(d)]):
        try:
            p = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, f"시간 초과({timeout}s)"
        if p.returncode != 0:
            return False, (p.stdout + p.stderr)[-1500:]
    return True, "tests+smoke ok"


def _sat_new_id(now: datetime) -> str:
    from core import satellite_lab as sl

    day = budget.kst(now).strftime("%Y%m%d")
    taken = {p.name for p in SAT_WS.glob(f"S-{day}-*")} | set(sl.load_registry()["variants"])
    i = 1
    while f"S-{day}-{i:03d}" in taken:
        i += 1
    return f"S-{day}-{i:03d}"


def sat_plan(now: datetime, done: set[tuple[str, str]]) -> Optional[tuple[str, str, dict]]:
    """새틀라이트 트랙의 다음 작업 하나(없으면 None). 파일·상태에서 매번 새로 계산한다."""
    from core import satellite_lab as sl

    def ok(role: str, key: str = "") -> bool:
        return (role, key) not in done and budget.can_launch(role, now)[0]

    from core import rnd_topics

    reg = sl.load_registry()
    in_flight = 0
    topic_counts = {t: 0 for t in sl.TOPICS}
    for d in sorted(p for p in SAT_WS.glob("S-*") if p.is_dir()):
        st0 = sl.agent_state(d.name)
        topic_counts[st0.get("topic", "selection")] = topic_counts.get(st0.get("topic", "selection"), 0) + 1
    for d in sorted(p for p in SAT_WS.glob("S-*") if p.is_dir()):
        sid = d.name
        st = sl.agent_state(sid)
        if sid in reg["variants"] or st.get("abandoned"):
            continue
        if not rnd_topics.sat_topic_on(st.get("topic", "selection")):
            continue  # R&D 센터에서 꺼진 주제 — 상태는 그대로 두고 다시 켜면 이어서
        cur = sl.variant_hash(d)
        if st.get("ready_hash") and st["ready_hash"] == cur:
            continue  # 준비 완료 — 계산기가 동결할 차례(주간 상한에 걸리면 다음 주)
        in_flight += 1
        rounds = st.get("rounds", 0)
        if cur is None:
            if rounds < SAT_MAX_ROUNDS and ok("sat_designer", sid):
                return "sat_designer", sid, {"feedback": "spec.json 또는 signal.py 가 없습니다. 계약대로 세 파일을 모두 쓰세요."}
            if rounds >= SAT_MAX_ROUNDS:
                sl.save_agent_state(sid, {**st, "abandoned": "파일 미완성"})
            continue
        if st.get("tested_hash") != cur:
            passed, msg = sat_check(sid)
            st.update(tested_hash=cur, test_ok=passed, test_msg=msg)
            sl.save_agent_state(sid, st)
        if not st.get("test_ok"):
            if rounds < SAT_MAX_ROUNDS and ok("sat_designer", sid):
                return "sat_designer", sid, {"feedback": f"결정론 검사 실패:\n{st.get('test_msg')}"}
            if rounds >= SAT_MAX_ROUNDS:
                sl.save_agent_state(sid, {**st, "abandoned": f"검사 실패 {SAT_MAX_ROUNDS}회"})
            continue
        if st.get("critic_hash") != cur:
            if ok("sat_critic", sid):
                return "sat_critic", sid, {"hash": cur}
            continue
        crit = _sat_critic(sid)
        if crit.get("verdict") == "approve":
            sl.save_agent_state(sid, {**st, "ready_hash": cur, "ready_at": now.isoformat()})
            in_flight -= 1
            continue
        if rounds < SAT_MAX_ROUNDS and ok("sat_designer", sid):
            return "sat_designer", sid, {"feedback": "Critic 반려:\n" + json.dumps(crit.get("issues", []), ensure_ascii=False)[:1500]}
        if rounds >= SAT_MAX_ROUNDS:
            sl.save_agent_state(sid, {**st, "abandoned": f"Critic 반려 {SAT_MAX_ROUNDS}회"})
    room = sl.WEEKLY_AGENT_FREEZE_CAP - sl.frozen_this_week(reg, now)
    enabled = rnd_topics.enabled_sat_topics()
    if enabled and in_flight < SAT_MAX_IN_FLIGHT and room > 0 and ok("sat_designer", "new"):
        topic = min(enabled, key=lambda t: (topic_counts.get(t, 0), sl.TOPICS.index(t)))
        return "sat_designer", _sat_new_id(now), {"new": True, "topic": topic}
    return None


# ---------------------------------------------------------------- AI 국제정세 의견 shadow (2026-10-02, core/geo_shadow.py)
def geo_plan(now: datetime, done: set[tuple[str, str]]) -> Optional[tuple[str, str, dict]]:
    """매달 25일 이후, 다음 달 의견이 원장에 없으면 geo_analyst 한 번. 초안이 이미 있으면 원장에 넣기만 한다."""
    from core import geo_shadow as gs

    from core import rnd_topics

    if not rnd_topics.is_on("geo_shadow"):
        return None
    month = gs.target_month(budget.kst(now).date())
    if month is None or gs.has_month(month):
        return None
    if (gs.DRAFT_DIR / f"{month}.json").exists():
        gs.ingest_draft(month, now=now)
        if gs.has_month(month):
            return None
    if ("geo_analyst", month) not in done and budget.can_launch("geo_analyst", now)[0]:
        return "geo_analyst", month, {}
    return None


# ---------------------------------------------------------------- 코어 분기 연구 (2026-10-05, core/core_rnd.py)
CORE_IDEAS_DIR = RESEARCH / "core_lab" / "ideas"


def core_plan(now: datetime, done: set[tuple[str, str]]) -> Optional[tuple[str, str, dict]]:
    """분기마다: 아이디어가 아직 없으면 core_designer 한 번, 모두 형식 오류였으면 그 분기에 한 번 더(재작업). 주제가 꺼져 있으면 없음."""
    from core import core_rnd as crd
    from core import rnd_topics

    if not rnd_topics.is_on("core_quarterly"):
        return None
    quarter = crd.quarter_of(budget.kst(now).date())
    st = crd.agent_state(quarter)
    synced = crd.sync_ideas(quarter, ideas_dir=CORE_IDEAS_DIR)
    if synced["frozen"] or synced["errors"]:
        st.setdefault("frozen", []).extend(synced["frozen"])
        st["errors"] = synced["errors"]
        crd.save_agent_state(quarter, st)
    runs = st.get("runs", 0)
    if st.get("frozen") or runs >= 2:
        return None
    if ("core_designer", quarter) in done or not budget.can_launch("core_designer", now)[0]:
        return None
    feedback = ("이전 제출의 형식 오류:\n" + json.dumps(st.get("errors"), ensure_ascii=False)[:1500]) if st.get("errors") else None
    return "core_designer", quarter, {"feedback": feedback}


def _write_core_context() -> None:
    from core import core_rnd as crd

    try:
        crd._atomic(RESEARCH / "core_lab" / "context.md", crd.context_markdown())
    except OSError:
        pass


def _sat_critic(sid: str) -> dict:
    try:
        return json.loads((SAT_WS / sid / "critic.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_sat_context() -> None:
    from core import satellite_lab as sl

    try:
        sl._atomic_write(sl.LAB_DIR / "context.md", sl.context_markdown())
    except OSError:
        pass


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
    SAT_WS.mkdir(parents=True, exist_ok=True)
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
        if role == "sat_designer":
            _write_sat_context()
        if role == "core_designer":
            _write_core_context()
            if extra.get("new"):
                done.add(("sat_designer", "new"))
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
        if role == "core_designer":
            from core import core_rnd as crd

            cst = crd.agent_state(hid)
            cst["runs"] = cst.get("runs", 0) + 1
            synced = crd.sync_ideas(hid, ideas_dir=CORE_IDEAS_DIR)
            cst.setdefault("frozen", []).extend(synced["frozen"])
            cst["errors"] = synced["errors"]
            crd.save_agent_state(hid, cst)
            log.append(f"코어 분기 아이디어 {hid}: 등록 {synced['frozen']} 오류 {list(synced['errors'])}")
        if role == "geo_analyst":
            from core import geo_shadow as gs

            _ok, msg = gs.ingest_draft(hid, now=now_fn())
            log.append(f"국제정세 의견: {msg}")
        if role in ("sat_designer", "sat_critic"):
            from core import satellite_lab as sl

            st = sl.agent_state(hid)
            if role == "sat_designer":
                st["rounds"] = st.get("rounds", 0) + 1
                if extra.get("topic"):
                    st.setdefault("topic", extra["topic"])
            else:
                st["critic_hash"] = extra["hash"] if sl.variant_hash(SAT_WS / hid) == extra["hash"] else None
            sl.save_agent_state(hid, st)
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
