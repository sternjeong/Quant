"""코어 연구실 (2026-10-05, 사용자 요청; 2026-10-10 세대 단위로 재설계) — AI 가 근거 있는 코어 아이디어(선정·보유 중 매도 시점)를
배치(세대)당 최대 BATCH_SIZE개 제안하고 같은 판정 규칙으로 계속 시험한다. 직전 세대가 전부 심판(통과/탈락)되면 그 결과·교훈을
바탕으로 다음 세대를 바로 쓴다(core.agent_batch.core_plan 이 "심판 대기 큐가 비었는가"로 다음 세대 시점을 정한다 — 달력 기준
아님). R&D 센터 주제 'core_quarterly' 로 켜고 끈다(끄면 제안·판정이 멈추고 대기열은 남는다).

왜 배치로 묶는가: 코어는 17개 ETF·월 1회 결정이라 18년에 결정이 약 220번뿐이라 매일 아이디어를 쏟아내면 우연히 맞는 규칙만
찾게 된다 — 한 번에 하나씩 부르지 않고 N개씩 묶어 호출 수(토큰)를 아끼면서도, 세대마다 심판 결과를 반영해 계속 이어가게 한다.

아이디어 형식(코드 없음 — 정해진 설정 범위 안의 조합만, 실수 여지를 줄인다): research/core_lab/ideas/<분기>/<id>.json
  {"id": "Q-2026q4-01", "title", "thesis", "source", "topic": "selection"|"exit",
   "config": {CoreConfig 의 일부 필드}, "exit_rule": {"kind": "none"|"trail"|"sma"|"mom_neg"|"rank"|"spy", ...},
   "neighbors": [설정 덮어쓰기 0~2개 — 강건성(G4) 확인용]}
엔진: core.core_lab(현 코어를 라이브 엔진과 일별 비중까지 같게 재현) + core.sprint_lab.apply_core_exits(보유 중 매도).
측정: 배당 포함 총수익, 남는 몫 BIL. 판정: core_lab.judge(core-judge/v1 관문 G1~G5) — 시도 수는 이 연구실 누적,
처음 값은 이미 코어에서 시험한 229개(core-rnd-v2 13 + sprint F2 180 + F3 22 + info A 14)에서 시작한다. 통과해도 자동 반영 없음.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IDEAS_DIR = PROJECT_ROOT / "research" / "core_lab" / "ideas"
STATE_DIR = PROJECT_ROOT / "data" / "core_lab"
PRIOR_CORE_TRIALS = 229
ID_RE = re.compile(r"^Q-(\d{4}q[1-4])-(\d{2})$")
BATCH_SIZE = 3
STATUS_QUEUED, STATUS_PASS, STATUS_FAIL, STATUS_ERROR = "queued", "pass", "fail", "error"

CONFIG_RULES: dict[str, Any] = {
    "lookbacks": ("list", 21, 378, 4),
    "abs_filter": ("enum", ("zero", "bil")),
    "top_n": ("int", 2, 6),
    "buffer_n": ("int_or_null", 3, 10),
    "corr_cap": ("float_or_null", 0.5, 0.95),
    "corr_window": ("int", 63, 252),
    "weighting": ("enum", ("equal", "inverse_vol")),
    "market_filter": ("enum", ("spy200", "none", "asset_sma", "credit")),
    "filter_window": ("int", 50, 400),
    "tranches": ("enum", (1, 2, 4)),
    "signal_basis": ("enum", ("price", "total")),
}
EXIT_RULES: dict[str, dict[str, tuple]] = {
    "none": {},
    "trail": {"p": ("float", 0.03, 0.30), "freq": ("enum", ("daily", "weekly"))},
    "sma": {"n": ("int", 10, 250), "freq": ("enum", ("daily", "weekly"))},
    "mom_neg": {"freq": ("enum", ("daily", "weekly"))},
    "rank": {"k": ("int", 5, 12), "freq": ("enum", ("daily", "weekly"))},
    "spy": {"freq": ("enum", ("daily", "weekly"))},
}


class CoreIdeaError(ValueError):
    pass


def quarter_of(d: date) -> str:
    return f"{d.year}q{(d.month - 1) // 3 + 1}"


def _check(name: str, val: Any, rule: tuple, errors: list[str]) -> Any:
    kind = rule[0]
    if kind == "enum":
        if val not in rule[1]:
            errors.append(f"{name}: {rule[1]} 중 하나")
        return val
    if kind in ("int", "int_or_null"):
        if val is None and kind == "int_or_null":
            return None
        if not isinstance(val, int) or isinstance(val, bool) or not (rule[1] <= val <= rule[2]):
            errors.append(f"{name}: {rule[1]}~{rule[2]} 정수")
        return val
    if kind in ("float", "float_or_null"):
        if val is None and kind == "float_or_null":
            return None
        if not isinstance(val, (int, float)) or isinstance(val, bool) or not (rule[1] <= val <= rule[2]):
            errors.append(f"{name}: {rule[1]}~{rule[2]}")
        return val
    if kind == "list":
        if not isinstance(val, list) or not (1 <= len(val) <= rule[3]) or not all(
                isinstance(x, int) and not isinstance(x, bool) and rule[1] <= x <= rule[2] for x in val):
            errors.append(f"{name}: {rule[1]}~{rule[2]} 정수 1~{rule[3]}개")
        return val
    raise ValueError(kind)


def _clean_config(cfg: dict, errors: list[str], label: str) -> dict:
    out = {}
    for k, v in (cfg or {}).items():
        if k not in CONFIG_RULES:
            errors.append(f"{label}.{k}: 바꿀 수 없는 항목(가능: {', '.join(CONFIG_RULES)})")
            continue
        out[k] = _check(f"{label}.{k}", v, CONFIG_RULES[k], errors)
    return out


def _clean_exit(rule: Optional[dict], errors: list[str], label: str) -> dict:
    rule = rule or {"kind": "none"}
    kind = rule.get("kind")
    if kind not in EXIT_RULES:
        errors.append(f"{label}.kind: {tuple(EXIT_RULES)} 중 하나")
        return {"kind": "none"}
    out = {"kind": kind}
    for k, r in EXIT_RULES[kind].items():
        out[k] = _check(f"{label}.{k}", rule.get(k), r, errors)
    return out


def validate_idea(idea: dict) -> dict:
    e: list[str] = []
    if not isinstance(idea, dict):
        raise CoreIdeaError("JSON 객체가 아님")
    if not ID_RE.match(str(idea.get("id", ""))):
        e.append("id: Q-YYYYqN-NN 형식(예 Q-2026q4-01)")
    for key, limit in (("title", 80), ("thesis", 500), ("source", 300)):
        v = str(idea.get(key) or "").strip()
        if not v or len(v) > limit:
            e.append(f"{key}: 1~{limit}자")
    if idea.get("topic", "selection") not in ("selection", "exit"):
        e.append("topic: selection 또는 exit")
    cfg = _clean_config(idea.get("config") or {}, e, "config")
    ex = _clean_exit(idea.get("exit_rule"), e, "exit_rule")
    if not cfg and ex["kind"] == "none":
        e.append("config 나 exit_rule 중 하나는 현 코어와 달라야 함")
    nbs = idea.get("neighbors") or []
    if not isinstance(nbs, list) or len(nbs) > 2:
        e.append("neighbors: 0~2개")
        nbs = []
    clean_nbs = []
    for i, nb in enumerate(nbs):
        if not isinstance(nb, dict):
            e.append(f"neighbors[{i}]: 객체")
            continue
        clean_nbs.append({"config": _clean_config(nb.get("config") or {}, e, f"neighbors[{i}].config"),
                          "exit_rule": _clean_exit(nb.get("exit_rule"), e, f"neighbors[{i}].exit_rule") if nb.get("exit_rule") else None})
    if e:
        raise CoreIdeaError("; ".join(e))
    return {"id": idea["id"], "title": str(idea["title"]).strip(), "thesis": str(idea["thesis"]).strip(),
            "source": str(idea["source"]).strip(), "topic": idea.get("topic", "selection"),
            "config": cfg, "exit_rule": ex, "neighbors": clean_nbs}


def build_config(cfg_over: dict):
    from core import core_lab as cl

    over = dict(cfg_over)
    return cl.with_changes(cl.CoreConfig(cash="bil"), **over)


# ---------------------------------------------------------------- 등록부
def _atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def load_registry(state_dir: Optional[Path] = None) -> dict:
    p = Path(state_dir or STATE_DIR) / "registry.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ideas": {}, "cumulative_trials": PRIOR_CORE_TRIALS, "updated_at": None}


@contextlib.contextmanager
def edit_registry(state_dir: Optional[Path] = None):
    d = Path(state_dir or STATE_DIR)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "registry.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        reg = load_registry(d)
        yield reg
        reg["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _atomic(d / "registry.json", json.dumps(reg, ensure_ascii=False, indent=1, default=str))


def freeze(idea: dict, origin: str = "agent", state_dir: Optional[Path] = None) -> dict:
    idea = validate_idea(idea)
    with edit_registry(state_dir) as reg:
        if idea["id"] in reg["ideas"]:
            return reg["ideas"][idea["id"]]
        reg["cumulative_trials"] = int(reg.get("cumulative_trials", PRIOR_CORE_TRIALS)) + 1
        entry = {"id": idea["id"], "origin": origin, "idea": idea, "status": STATUS_QUEUED, "attempts": 0,
                 "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "result": None, "notified": False}
        reg["ideas"][idea["id"]] = entry
        return entry


def next_batch_ids(quarter: str, n: int, known: Optional[set] = None, state_dir: Optional[Path] = None) -> list[str]:
    """그 분기 안에서 아직 안 쓴 id n개(Q-<분기>-NN, 순차). known 은 추가로 피할 id(예: 심판 대기 중인 직전 배치)."""
    taken = set(load_registry(state_dir)["ideas"]) | (known or set())
    out, i = [], 1
    while len(out) < n and i < 1000:
        cid = f"Q-{quarter}-{i:02d}"
        if cid not in taken:
            out.append(cid)
        i += 1
    return out


def sync_ideas(quarter: str, ids: Optional[list[str]] = None, ideas_dir: Optional[Path] = None,
               state_dir: Optional[Path] = None) -> dict:
    """지정된 id(한 세대/배치)의 아이디어 파일을 검증·동결한다. {"frozen": [...], "errors": {id: 사유}}.

    `ids` 를 안 주면(이전 호환) 그 분기 폴더를 그대로 훑어 최대 BATCH_SIZE개까지 처리한다 — 다만 이 경로는
    세대 추적이 없어 한 분기에 영원히 처음 BATCH_SIZE개만 본다(옛 동작). 세대별 반복 호출은 반드시 `ids`를 준다.
    """
    d = Path(ideas_dir or IDEAS_DIR) / quarter
    out: dict[str, Any] = {"frozen": [], "errors": {}}
    known = load_registry(state_dir)["ideas"]
    candidates = ([d / f"{i}.json" for i in ids] if ids is not None
                  else sorted(d.glob("Q-*.json"))[:BATCH_SIZE])
    for f in candidates:
        if f.stem in known or not f.is_file():
            continue
        try:
            idea = json.loads(f.read_text(encoding="utf-8"))
            if idea.get("id") != f.stem:
                raise CoreIdeaError(f"id 불일치({idea.get('id')} ≠ 파일 {f.stem})")
            freeze(idea, "agent", state_dir)
            out["frozen"].append(f.stem)
        except (ValueError, CoreIdeaError) as exc:
            out["errors"][f.stem] = str(exc)[:500]
    return out


def queue(reg: dict) -> list[dict]:
    return sorted((v for v in reg["ideas"].values() if v["status"] == STATUS_QUEUED), key=lambda v: v["frozen_at"])


def has_work(state_dir: Optional[Path] = None) -> bool:
    from core import rnd_topics

    return rnd_topics.is_on("core_quarterly") and bool(queue(load_registry(state_dir)))


def agent_state(quarter: str, state_dir: Optional[Path] = None) -> dict:
    try:
        return json.loads((Path(state_dir or STATE_DIR) / "agent" / f"{quarter}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_agent_state(quarter: str, st: dict, state_dir: Optional[Path] = None) -> None:
    _atomic(Path(state_dir or STATE_DIR) / "agent" / f"{quarter}.json", json.dumps(st, ensure_ascii=False, indent=1))


def context_markdown(state_dir: Optional[Path] = None) -> str:
    reg = load_registry(state_dir)
    lines = ["# 코어 분기 연구 현황 (자동 생성)", "",
             f"- 누적 시도 수 N = {reg.get('cumulative_trials')} (이전 코어 연구 {PRIOR_CORE_TRIALS}개 포함 — 클수록 통과 기준이 엄격)",
             "- 이미 시험해 탈락한 방향(research/results/ 참고): 남는 몫 BIL(C01, G1 만 탈락 → 사용자 결정으로 반영됨), 4분할·기간 혼합·상관 제한·순위 완충·"
             "3/5종목·변동성 반비례·자산별 추세·신용 필터·총수익 순위(core-rnd-v2), 9개월·5종목 등 180조합(sprint F2, PBO 57%), 보유 중 매도 22가지(sprint F3, 전부 현 규칙보다 나쁨), "
             "VIX·실현변동성 급락 필터(info A, 오신호로 전부 탈락)", "", "| id | 상태 | 아이디어 | 사유 |", "|---|---|---|---|"]
    for v in reg["ideas"].values():
        res = v.get("result") or {}
        lines.append(f"| {v['id']} | {v['status']} | {v['idea']['title']} | {'; '.join(res.get('reasons') or [])[:200]} |")
    return "\n".join(lines) + "\n"


def notification_text(entry: dict) -> str:
    res = entry.get("result") or {}
    head = {"pass": "✅ 통과 — 사람 검토 대기", "fail": "❌ 탈락", "error": "⚠️ 계산 오류"}.get(entry["status"], entry["status"])
    lines = [f"[코어 분기 연구] {entry['id']} {entry['idea']['title']} — {head}"]
    for r in (res.get("reasons") or [])[:3]:
        lines.append(f"· {r}")
    if entry["status"] == STATUS_PASS:
        lines.append("챔피언에는 자동 반영되지 않습니다.")
    return "\n".join(lines)[:1200]
