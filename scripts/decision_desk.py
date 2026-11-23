"""판단판 만들기 — 시장·내 포트폴리오·보유·관심 종목의 앞으로 1·3·6·12개월 분포와 사건 확률을 계산해 저장한다.

보유 종목·현금·관심 종목은 DB 에서, 가격은 가격 저장소(없으면 받아서)에서 읽고, 검증 연구 desk-engine-v1 의 모형으로 계산해
data/decision_desk/latest.json 에 쓴다(관제 센터 '판단판' 화면이 읽는다). 같은 날 같은 자산의 예측은 history.jsonl 에 한 번만
덧붙여 나중에 실제 결과와 맞춰 볼 수 있게 한다. 매수·매도를 정해 주지 않고, 주문·챔피언 전략·아침 메시지는 건드리지 않는다.

    python scripts/decision_desk.py              # 계산해 저장하고 요약을 보여 준다
    python scripts/decision_desk.py --dry-run    # 저장하지 않고 요약만
    python scripts/decision_desk.py --tickers NVDA,AAPL --dry-run   # 보유·관심 대신 지정한 종목만(DB 를 읽지 않는다)
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import decision_desk as dd  # noqa: E402

HISTORY_YEARS = 6
EXTRA = ("QQQ",)               # 보유·관심과 무관하게 늘 함께 보는 자산


def load_prices(tickers: list) -> tuple:
    """{티커: 로그 수정 종가}, {티커: 마지막 종가}. 못 받은 티커는 빠진다."""
    from core.market_data import get_price_history

    start = (date.today() - timedelta(days=366 * HISTORY_YEARS)).isoformat()
    prices, closes = {}, {}
    for t in tickers:
        try:
            df = get_price_history(t, start=start, interval="1d")
        except Exception:  # noqa: BLE001 — 한 종목이 실패해도 나머지는 계산한다
            continue
        if df is None or df.empty:
            continue
        adj = df["Adj Close"] if "Adj Close" in df.columns else df["Close"]
        close = df["Close"] if "Close" in df.columns else adj
        if isinstance(adj, pd.DataFrame):
            adj = adj.iloc[:, 0]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        adj = adj.astype(float)
        adj = adj[adj > 0].dropna()
        if adj.empty:
            continue
        idx = pd.DatetimeIndex(adj.index)
        adj.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
        prices[t] = np.log(adj[~adj.index.duplicated(keep="last")].sort_index())
        last = close.astype(float).dropna()
        if not last.empty:
            closes[t] = float(last.iloc[-1])
    return prices, closes


def crash_lines() -> list:
    """급락 예측 기록기의 상태 한 줄과 기록(있으면). 실패하면 빈 목록."""
    try:
        from scripts import crash_forecast_log as cfl

        ctx, data = cfl.build()
        lines = [cfl.status_line(ctx, data)]
        logged = cfl.read_log()
        if logged:
            lines += cfl.report(ctx, logged).splitlines()
        return lines
    except Exception as exc:  # noqa: BLE001
        return [f"급락 상황을 읽지 못함({type(exc).__name__})"]


def _pct(x: Optional[float], digits: int = 0) -> str:
    return "—" if x is None else f"{x * 100:+.{digits}f}%"


def _p(x: Optional[float]) -> str:
    return "—" if x is None else f"{x * 100:.0f}%"


def summary_lines(snap: dict) -> list:
    if snap.get("status") != "ok":
        return [snap.get("message", "판단판을 만들지 못했습니다.")]
    out = [f"판단판 기준일 {snap.get('asof')} · 모형 {snap['model']['study']}(자료 {snap['model']['data_end']}까지)"]
    for sh in [snap["market"], snap.get("portfolio")] + snap["positions"] + snap["watch"]:
        if not sh:
            continue
        if sh.get("error"):
            out.append(f"  {sh['ticker']}: {sh['error']}")
            continue
        r = next((x for x in sh["horizons"] if x["h"] == 63), None)
        if r is None:
            continue
        beat = "" if "beat" not in r["p"] else f" · 시장 이길 확률 {_p(r['p']['beat'])}"
        out.append(f"  {sh['ticker']}: 3개월 {_pct(r['q'][0])} ~ {_pct(r['q'][4])}(중앙 {_pct(r['q'][2])}) · 오를 확률 {_p(r['p'].get('up'))} · "
                   f"15% 이상 빠질 확률 {_p(r['p'].get('dd15'))}(과거 평균 {_p(r['p_base'].get('dd15'))}){beat}")
    ls = snap.get("live_score") or {}
    for r in ls.get("horizons", []):
        out.append(f"  실전 기록 {r['h']}거래일: {r['n']}건 · 10~90% 범위 적중 {r['coverage80'] * 100:.0f}%(목표 80%)")
    if ls and not ls.get("horizons"):
        out.append(f"  실전 기록: 기간이 다 지난 예측이 아직 없음(대기 {ls.get('pending', 0)}건)")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--tickers", default="", help="쉼표로 구분한 종목 — 보유·관심 대신 이 종목만 본다")
    p.add_argument("--model-dir", default=str(dd.MODEL_DIR))
    p.add_argument("--out-dir", default=str(dd.OUT_DIR))
    a = p.parse_args(argv)
    holdings, watch, cash = [], [], 0.0
    if a.tickers:
        watch = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]
    else:
        from core import portfolio, watchlist

        holdings, cash = portfolio.list_holdings(), portfolio.get_cash_balance()
        watch = [w["ticker"] for w in watchlist.list_watchlist()]
    held = sorted({str(h["ticker"]).upper() for h in holdings})
    tickers = list(dict.fromkeys([dd.MARKET_TICKER] + held + [t.upper() for t in watch] + list(EXTRA)))
    model = dd.load_model(Path(a.model_dir))
    prices, closes = load_prices(tickers) if model is not None else ({}, {})
    snap = dd.build_snapshot(model, prices, closes, holdings, list(watch) + list(EXTRA), cash, crash_lines())
    snap["live_score"] = dd.score_history(dd.read_history(Path(a.out_dir)), prices)
    print("\n".join(summary_lines(snap)))
    if a.dry_run:
        print("(--dry-run: 저장하지 않음)")
        return 0
    n = dd.write_snapshot(snap, Path(a.out_dir))
    print(f"저장 → {Path(a.out_dir) / dd.SNAPSHOT_NAME} (예측 기록 {n}줄 추가)")
    return 0 if snap.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
