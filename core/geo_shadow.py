"""AI 국제정세 의견 shadow 원장 (2026-10-02) — 매달 코어 리밸런싱 전에 AI 가 17자산에 대한 정세 의견을 남기고,
**배분에는 반영하지 않은 채** 결과를 기다려 사전 고정 규칙으로 판정한다.

왜 shadow 인가: AI 는 과거 사건의 결말을 이미 알고 있어 과거 데이터로 정직하게 검증할 수 없다. 그래서 결과를 모르는 시점에
시각을 찍어 기록하고(앞으로만), 쌓인 뒤에 판정한다.

흐름: 야간 에이전트 배치(geo_analyst, 매달 25일 이후 한 번) → research/geo_shadow/<YYYY-MM>.json → 배치가 검증 후
data/geo_shadow/ledger.jsonl 에 기록(에이전트가 쓸 수 없는 곳, 달마다 첫 기록만 인정·수정 불가) → 챔피언 화면에 '의견(배분 미반영)'으로 표시
→ evaluate() 가 다음 달 실제 수익으로 채점.

판정 geo-judge/v1 (2026-10-02 고정, 결과를 보기 전): 기록이 MIN_MONTHS(24)개월 쌓이기 전에는 판정하지 않는다.
  - 조정안: 그 달 현 코어 top4 중 AI 가 −1 을 준 자산을 빼고 그 몫을 단기국채(BIL)로 → 규칙 그대로와 월 수익 차이
  - PASS = 월 수익 차이 평균 > 0 이고 t ≥ 2.0, 그리고 0 아닌 의견의 적중률(−1 은 17자산 평균보다 못함, +1 은 나음) ≥ 55% 이면서
    이항검정 단측 p ≤ 0.05. 통과해도 '제한적 반영(4종목 중 최대 1개 축소만)'을 사람이 검토할 후보일 뿐이다.
주문 경로와 연결되어 있지 않다.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from core.champion_strategy import CORE_UNIVERSE

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DRAFT_DIR = PROJECT_ROOT / "research" / "geo_shadow"
LEDGER = PROJECT_ROOT / "data" / "geo_shadow" / "ledger.jsonl"
JUDGE_VERSION = "geo-judge/v1"
MIN_MONTHS = 24
T_THRESHOLD = 2.0
HIT_RATE = 0.55
BINOM_P = 0.05
MAX_NONZERO = 6
DUE_FROM_DAY = 25  # 그 달 25일부터 다음 달 의견을 받는다(다음 달 첫 거래일 리밸런싱 전)
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


class GeoRecordError(ValueError):
    pass


def target_month(today: date) -> Optional[str]:
    """의견을 받을 달(다음 달). 25일 전이면 None."""
    if today.day < DUE_FROM_DAY:
        return None
    nxt = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    return nxt.strftime("%Y-%m")


def validate(rec: dict, month: str) -> dict:
    e: list[str] = []
    if not isinstance(rec, dict):
        raise GeoRecordError("JSON 객체가 아님")
    if rec.get("month") != month:
        e.append(f"month 는 {month} 이어야 함")
    views = rec.get("assets")
    if not isinstance(views, dict) or set(views) != set(CORE_UNIVERSE):
        e.append(f"assets 는 코어 {len(CORE_UNIVERSE)}자산 전부를 키로 가져야 함({', '.join(CORE_UNIVERSE)})")
    else:
        nonzero = 0
        for t, v in views.items():
            if not isinstance(v, dict) or v.get("view") not in (-1, 0, 1):
                e.append(f"{t}.view 는 -1/0/1")
                continue
            c = v.get("confidence")
            if not isinstance(c, (int, float)) or not (0 <= c <= 1):
                e.append(f"{t}.confidence 는 0~1")
            if v["view"] != 0:
                nonzero += 1
                if not str(v.get("reason") or "").strip():
                    e.append(f"{t}.reason 필요(0 이 아닌 의견)")
        if nonzero > MAX_NONZERO:
            e.append(f"0 이 아닌 의견은 최대 {MAX_NONZERO}개(지금 {nonzero})")
    if not str(rec.get("summary") or "").strip() or len(str(rec.get("summary"))) > 1500:
        e.append("summary 1~1500자")
    src = rec.get("sources")
    if not isinstance(src, list) or not src or not all(isinstance(s, str) and s.startswith("http") for s in src):
        e.append("sources: http 로 시작하는 근거 URL 목록(1개 이상)")
    if e:
        raise GeoRecordError("; ".join(e))
    return {"month": month, "assets": {t: {"view": int(v["view"]), "confidence": float(v["confidence"]),
                                           "reason": str(v.get("reason") or "")[:400]} for t, v in views.items()},
            "summary": str(rec["summary"]), "sources": list(src)[:20]}


def load_ledger(path: Optional[Path] = None) -> list[dict]:
    p = Path(path or LEDGER)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def has_month(month: str, path: Optional[Path] = None) -> bool:
    return any(r.get("month") == month for r in load_ledger(path))


def record(rec: dict, month: str, *, path: Optional[Path] = None, now: Optional[datetime] = None) -> dict:
    """검증 후 원장에 한 줄 추가. 같은 달 기록이 이미 있으면 그대로 둔다(수정 불가)."""
    clean = validate(rec, month)
    p = Path(path or LEDGER)
    existing = [r for r in load_ledger(p) if r.get("month") == month]
    if existing:
        return existing[0]
    now = now or datetime.now(timezone.utc)
    clean["recorded_at"] = now.isoformat(timespec="seconds")
    clean["judge_version"] = JUDGE_VERSION
    clean["sha"] = hashlib.sha256(json.dumps(clean, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(clean, ensure_ascii=False) + "\n")
    return clean


def ingest_draft(month: str, *, draft_dir: Optional[Path] = None, path: Optional[Path] = None,
                 now: Optional[datetime] = None) -> tuple[bool, str]:
    """에이전트 초안(research/geo_shadow/<month>.json)을 원장에 넣는다. (성공 여부, 메시지)."""
    f = Path(draft_dir or DRAFT_DIR) / f"{month}.json"
    if not f.exists():
        return False, "초안 없음"
    try:
        rec = record(json.loads(f.read_text(encoding="utf-8")), month, path=path, now=now)
    except (ValueError, GeoRecordError) as exc:
        return False, f"초안 거부: {str(exc)[:300]}"
    nz = {t: v["view"] for t, v in rec["assets"].items() if v["view"]}
    return True, f"{month} 의견 기록({rec['recorded_at']}): {nz or '전부 중립'}"


def latest(path: Optional[Path] = None) -> Optional[dict]:
    rows = load_ledger(path)
    return max(rows, key=lambda r: r["month"]) if rows else None


# ---------------------------------------------------------------- 채점
def _binom_sf(k: int, n: int, p: float = 0.5) -> float:
    """P(X >= k), X~Bin(n, p)."""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def evaluate(rows: list[dict], monthly_returns: pd.DataFrame, top4_by_month: dict[str, list[str]],
             cash_returns: Optional[pd.Series] = None) -> dict:
    """monthly_returns: 행=월('YYYY-MM'), 열=17자산 그 달 총수익. top4_by_month: 그 달 현 코어 보유.
    결과가 아직 없는 달(다음 달이 안 끝남)은 건너뛴다."""
    diffs, hits, calls, months = [], 0, 0, []
    for r in sorted(rows, key=lambda x: x["month"]):
        m = r["month"]
        if m not in monthly_returns.index or m not in top4_by_month:
            continue
        ret = monthly_returns.loc[m]
        top4 = top4_by_month[m]
        cash = float(cash_returns.get(m, 0.0)) if cash_returns is not None else 0.0
        rule = sum(float(ret.get(t, 0.0)) for t in top4) / 4
        adj = sum((cash if r["assets"].get(t, {}).get("view") == -1 else float(ret.get(t, 0.0))) for t in top4) / 4
        diffs.append(adj - rule)
        avg = float(ret[list(CORE_UNIVERSE)].mean())
        for t, v in r["assets"].items():
            if v["view"] == 0 or pd.isna(ret.get(t)):
                continue
            calls += 1
            hits += int((ret[t] - avg) * v["view"] > 0)
        months.append(m)
    n = len(diffs)
    out: dict[str, Any] = {"judge_version": JUDGE_VERSION, "months_scored": n, "min_months": MIN_MONTHS,
                           "calls": calls, "hits": hits, "hit_rate": (hits / calls) if calls else None}
    if n >= 2:
        s = pd.Series(diffs)
        sd = float(s.std(ddof=1))
        out.update(mean_monthly_diff=float(s.mean()), t_stat=float(s.mean() / (sd / math.sqrt(n))) if sd > 0 else None)
    out["binom_p"] = _binom_sf(hits, calls) if calls else None
    if n < MIN_MONTHS:
        out["verdict"] = f"판정 전 ({n}/{MIN_MONTHS}개월)"
        return out
    ok = (out.get("mean_monthly_diff", 0) > 0 and (out.get("t_stat") or 0) >= T_THRESHOLD
          and (out["hit_rate"] or 0) >= HIT_RATE and (out["binom_p"] if out["binom_p"] is not None else 1) <= BINOM_P)
    out["verdict"] = "PASS" if ok else "FAIL"
    return out
