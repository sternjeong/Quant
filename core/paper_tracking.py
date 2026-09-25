"""core/paper_tracking.py — paper 계좌 실제 자산곡선 vs 챔피언 가상 원장의 추적오차(로드맵 P1, 관측 전용).

두 원료를 같은 날짜 축에 놓는다.
- 실제: core.models.AccountSnapshot(source=alpaca_paper) 의 날짜별 equity (00:35 KST account_snapshot_sync)
- 가상: core.models.ChampionLedgerEntry 의 날짜별 realized_return_pct (00:12 KST champion_ledger_record)
두 잡 모두 같은 KST 날짜의 밤에 기록하므로 같은 날짜끼리 맞춘다.

구간 (t-1, t] 마다 실제 수익 = equity_t / equity_{t-1} - 1, 가상 수익 = 그 구간 원장 일수익의 곱이다.
스냅샷이 빠진 날이 있어도 구간을 늘려 비교하므로 결측이 수익을 왜곡하지 않는다.

정직성 규칙:
- 추적오차(연율 표준편차)는 구간 n >= MIN_INTERVALS(20) 일 때만 계산한다. 미만이면 None.
- 괴리의 '분해'는 하지 않는다. 슬리피지(cost_calibration)·목표 이탈(drift_summary)·배당 시차는 원인 후보를
  나란히 보여주는 context 일 뿐이며 합이 괴리와 같다고 주장하지 않는다.
- paper 계좌가 포지션을 들고 있지 않으면(following=False) 괴리는 "전략을 따르지 않았음"이지 실행 품질이 아니다.
- paper 계좌의 입출금은 추적하지 않는다(paper 는 보통 없음). 수동 입금이 있으면 그 구간 수익이 틀린다.
조회·계산 전용이며 주문 경로를 import 하지 않는다.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

MIN_INTERVALS = 20
TRADING_DAYS = 252
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "cache" / "paper_tracking.json"
SOURCE = "alpaca_paper"


def compute_tracking(paper: list[tuple[date, float]], champion: list[tuple[date, float]]) -> dict[str, Any]:
    """paper=[(날짜, equity)], champion=[(날짜, 그날 실현 일수익 %)] → 구간별 비교와 요약."""
    pts = sorted({d: e for d, e in paper if e and e > 0}.items())
    champ = sorted(champion)
    intervals = []
    for (d0, e0), (d1, e1) in zip(pts, pts[1:]):
        growth, days = 1.0, 0
        for d, r in champ:
            if d0 < d <= d1:
                growth *= 1.0 + r / 100.0
                days += 1
        if days == 0:
            continue  # 가상 원장이 그 구간을 기록하지 않았다 → 비교 불가, 건너뜀
        paper_ret, champ_ret = e1 / e0 - 1.0, growth - 1.0
        intervals.append({"start": d0.isoformat(), "end": d1.isoformat(), "ledger_days": days,
                          "paper_return_pct": round(paper_ret * 100, 4), "champion_return_pct": round(champ_ret * 100, 4),
                          "diff_pct_points": round((paper_ret - champ_ret) * 100, 4)})
    n = len(intervals)
    paper_cum = champ_cum = 1.0
    for iv in intervals:
        paper_cum *= 1 + iv["paper_return_pct"] / 100
        champ_cum *= 1 + iv["champion_return_pct"] / 100
    te = None
    if n >= MIN_INTERVALS:
        diffs = [iv["diff_pct_points"] for iv in intervals]
        mean = sum(diffs) / n
        sd = math.sqrt(sum((x - mean) ** 2 for x in diffs) / (n - 1))
        avg_days = sum(iv["ledger_days"] for iv in intervals) / n
        te = round(sd * math.sqrt(TRADING_DAYS / avg_days), 4)
    return {
        "n_intervals": n, "min_intervals_for_te": MIN_INTERVALS,
        "paper_cum_return_pct": round((paper_cum - 1) * 100, 4) if n else None,
        "champion_cum_return_pct": round((champ_cum - 1) * 100, 4) if n else None,
        "cum_gap_pct_points": round((paper_cum - champ_cum) * 100, 4) if n else None,
        "tracking_error_annual_pct": te,
        "te_status": "ok" if te is not None else "insufficient_sample",
        "intervals": intervals,
    }


def _context(latest_snapshot: Any) -> dict[str, Any]:
    """괴리 원인 '후보'. 분해가 아니다."""
    ctx: dict[str, Any] = {"note": "원인 후보를 나란히 둔 것이며 합이 괴리와 같다는 뜻이 아니다. 배당 시차는 측정하지 않는다."}
    if latest_snapshot is not None:
        try:
            drift = json.loads(latest_snapshot.drift_summary or "{}")
        except ValueError:
            drift = {}
        ctx["latest_drift"] = {k: drift.get(k) for k in ("max_abs_drift_pct_points", "turnover_needed_pct", "n_unknown")}
        ctx["following"] = bool(latest_snapshot.n_positions)
    try:
        from core.cost_calibration import load_cost_calibration

        cal = load_cost_calibration()
        ctx["slippage"] = ({"status": cal.get("status"), "n": cal.get("n"),
                            "one_way_bps": (cal.get("scenario") or {}).get("slippage_bps")} if cal else {"status": "no_file"})
    except Exception as exc:  # noqa: BLE001
        ctx["slippage"] = {"status": f"unavailable:{type(exc).__name__}"}
    return ctx


def refresh_paper_tracking(session=None, save_path: Optional[str | Path] = None) -> dict[str, Any]:
    """DB 에서 두 원료를 읽어 계산하고 JSON 으로 저장한다."""
    from core.models import AccountSnapshot, ChampionLedgerEntry

    def _run(db) -> dict[str, Any]:
        snaps = (db.query(AccountSnapshot).filter(AccountSnapshot.source == SOURCE, AccountSnapshot.as_of.isnot(None))
                 .order_by(AccountSnapshot.as_of, AccountSnapshot.id).all())
        ledger = db.query(ChampionLedgerEntry).order_by(ChampionLedgerEntry.entry_date).all()
        res = compute_tracking([(s.as_of, s.equity) for s in snaps if s.equity],
                               [(e.entry_date, e.realized_return_pct) for e in ledger])
        res["context"] = _context(snaps[-1] if snaps else None)
        res["n_snapshots"], res["n_ledger_entries"] = len(snaps), len(ledger)
        return res

    if session is not None:
        res = _run(session)
    else:
        from core.db import get_session, init_db

        init_db()
        with get_session() as db:
            res = _run(db)
    res["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = Path(save_path) if save_path else DEFAULT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    res["path"] = str(path)
    return res


def summarize(res: dict[str, Any]) -> str:
    if not res.get("n_intervals"):
        return f"비교 구간 없음 (스냅샷 {res.get('n_snapshots', 0)}건, 원장 {res.get('n_ledger_entries', 0)}건)"
    te = res["tracking_error_annual_pct"]
    return (f"구간 {res['n_intervals']}개: paper {res['paper_cum_return_pct']:+.2f}% vs 챔피언 "
            f"{res['champion_cum_return_pct']:+.2f}% (괴리 {res['cum_gap_pct_points']:+.2f}%p), 추적오차 "
            + (f"{te:.2f}%/년" if te is not None else f"표본 부족(n<{MIN_INTERVALS})"))
