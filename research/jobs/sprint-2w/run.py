"""2주 R&D 스프린트 (사전 등록, 2026-10-02) — 넓게 찾고, 엄격하게 고른다.

## 사전 등록 (결과를 보기 전에 고정 — 바꾸려면 새 id)
탐색 공간은 core/sprint_lab.py 의 격자가 전부다(F1 새틀라이트 선정, F2 코어 선정, F3 코어 보유 중 매도, F4 매매 가격).
측정: 코어는 배당 포함 총수익(Adj Close), 남는 몫 BIL. 새틀라이트는 satellite_lab 시뮬레이터(가격 기준, 편도 8bp).
기간: 코어 2008-01~, 새틀라이트 2010-08~. 떼어 둔 구간 = 마지막 2년.
판정 sprint-judge/v1 (가족마다 승자 하나, 모두 만족해야 CANDIDATE = 사람 검토 후보, 엔진 자동 반영 없음):
  1) 승자 = 앞 구간(IS)에서 가장 좋은 설정(F1~F3 연샤프, F4 칸별 평균 개선)
  2) 승자의 현 규칙 대비 초과의 Deflated Sharpe ≥ 0.95 — 시도 수 = 그 가족 설정 수, 시도 간 분산 = 실제로 시도한 설정들의 분산
  3) CSCV 과적합 확률 PBO ≤ 25% (IS 를 8블록으로 나눠 70가지 조합)
  4) 떼어 둔 2년(탐색 뒤 한 번만 봄): 승자 샤프 > 현 규칙 샤프 (F4 는 평균 개선 > 0)
코어 가족(F2·F3)의 샤프는 단기국채(BIL) 대비 초과수익으로 잰다(현금성 비중이 큰 설정이 낮은 변동성만으로 유리해지지 않게 —
실제 데이터 실행 전 2026-10-02 고정). 새틀라이트(F1)는 남는 몫이 수익 0 현금이라 그대로다.
마감: 2026-10-16 23:50 KST. 그때까지 못 끝낸 설정은 빼고 끝난 것만으로 판정하며 그 수를 보고서에 적는다.
가족이 끝날 때마다 텔레그램 한 줄(진행 알림). 결과 파일은 계산이 다 끝났을 때만 쓴다(종료 코드 0).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import champion_strategy as cs  # noqa: E402
from core import core_lab as cl  # noqa: E402
from core import satellite_lab as sl  # noqa: E402
from core import sprint_lab as sp  # noqa: E402

KST = ZoneInfo("Asia/Seoul")
SPRINT_END = datetime(2026, 10, 16, 23, 50, tzinfo=KST)
CORE_START, SAT_START, SAT_COMMON = "2008-01-01", "2010-01-01", "2010-08-01"
FAMILIES = ("F2_core_select", "F3_core_exit", "F4_execution", "F1_satellite")  # 빠른 것부터
EXIT_IN_PROGRESS = 3


def log(m):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {m}", flush=True)


def deadline() -> float:
    raw = os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH")
    return (float(raw) if raw else time.time() + 3 * 3600) - 120


def notify(text: str, smoke: bool) -> None:
    if smoke:
        return
    try:
        from core.telegram_notify import send_message

        send_message(text[:1000])
    except Exception:  # noqa: BLE001
        pass


class Store:
    """가족별 결과를 체크포인트 폴더에 설정 하나당 한 파일로 저장(원자적 쓰기)."""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def path(self, fam: str, i: int) -> Path:
        return self.root / fam / f"{i:05d}.npy"

    def has(self, fam: str, i: int) -> bool:
        return self.path(fam, i).exists()

    def save(self, fam: str, i: int, arr: np.ndarray) -> None:
        p = self.path(fam, i)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp.npy")
        np.save(tmp, arr.astype(np.float32))
        os.replace(tmp, p)

    def load(self, fam: str, i: int) -> np.ndarray:
        return np.load(self.path(fam, i))

    def meta(self) -> dict:
        p = self.root / "meta.json"
        return json.loads(p.read_text()) if p.exists() else {"notified": []}

    def save_meta(self, m: dict) -> None:
        (self.root / "meta.json").write_text(json.dumps(m))


# ---------------------------------------------------------------- 데이터
def load_core(smoke: bool):
    tickers = list(cs.CORE_UNIVERSE) + [cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF]
    if smoke:
        idx = pd.bdate_range("2006-01-02", "2016-12-30")
        rng = np.random.default_rng(4)
        hist = {}
        for t in tickers:
            c = 50 * np.exp(np.cumsum(rng.normal(0.0003, 0.011, len(idx))))
            o = c * np.exp(rng.normal(0, 0.004, len(idx)))
            hist[t] = pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.005, "Low": np.minimum(o, c) * 0.995,
                                    "Close": c, "Adj Close": c * np.exp(np.cumsum(np.full(len(idx), 0.00005))), "Volume": 1e6}, index=idx)
    else:
        from core.market_data import get_multiple_price_history

        hist = get_multiple_price_history(tickers, start="2006-01-01", end=None, interval="1d")
    names = [t for t in tickers if t in hist and not hist[t].empty]
    price = cs._closes_from_histories(hist, names)
    total = cs._closes_from_histories(hist, names, field=cs.CORE_PRICE_FIELD)
    core = [t for t in cs.CORE_UNIVERSE if t in names]
    ex = [t for t in (cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF, *cl.CREDIT_PAIR) if t in names]
    return hist, (price[core], price[ex]), (total[core], total[ex])


def load_satellite(smoke: bool, pools: set[str]):
    if smoke:
        pp, poolp = sl.synthetic_providers(n_tickers=30, start="2008-01-01", end="2016-12-30")
        return sl.build_data(pools, start="2010-01-01", end="2016-12-30", pool_provider=poolp, price_provider=pp)
    return sl.build_data(pools, start=SAT_START, log=log)


# ---------------------------------------------------------------- 가족 계산
def core_index(price) -> pd.DatetimeIndex:
    return price[0].index[price[0].index >= pd.Timestamp(CORE_START)]


def run_family(fam: str, store: Store, ctx: dict, dl: float, smoke: bool) -> bool:
    """이 가족의 남은 설정을 계산한다. 다 끝났으면 True, 시간이 모자라면 False."""
    if fam == "F2_core_select":
        price, total = ctx["core_price"], ctx["core_total"]
        cfgs = sp.core_configs()
        for i, (name, cfg) in enumerate(cfgs):
            if store.has(fam, i):
                continue
            if time.time() > dl:
                return False
            r = cl.run(price[0], price[1], cfg, ctx["core_start"], total=total)
            store.save(fam, i, (r - ctx["cash_r"]).reindex(ctx["core_idx"]).fillna(0.0).to_numpy())
        return True
    if fam == "F3_core_exit":
        price, total = ctx["core_price"], ctx["core_total"]
        base_w = cl.build_weights(price[0], price[1], cl.CoreConfig(cash="bil"))
        for i, (name, rule) in enumerate(sp.core_exit_rules()):
            if store.has(fam, i):
                continue
            if time.time() > dl:
                return False
            w = sp.apply_core_exits(base_w, price[0], price[1][cs.MARKET_FILTER_TICKER], rule)
            rc, re = total
            keep = rc.index >= pd.Timestamp(ctx["core_start"])
            r = cl.portfolio_returns(rc[keep], re[keep], w.reindex(rc.index).fillna(0.0)[keep])
            store.save(fam, i, (r - ctx["cash_r"]).reindex(ctx["core_idx"]).fillna(0.0).to_numpy())
        return True
    if fam == "F1_satellite":
        data = ctx["sat_data"]()
        idx = ctx["sat_idx"](data)
        for i, c in enumerate(sp.satellite_configs()):
            if store.has(fam, i):
                continue
            if time.time() > dl:
                return False
            if smoke and i > 60 and sp.satellite_config_name(c) != sp.SATELLITE_INCUMBENT:
                store.save(fam, i, np.full(len(idx), np.nan))  # 스모크는 앞쪽 일부만 실제 계산
                continue
            r = sp.run_satellite_config(c, data)
            store.save(fam, i, r.reindex(idx).fillna(0.0).to_numpy())
        return True
    if fam == "F4_execution":
        p = store.root / fam / "cells.pkl"
        if p.exists():
            return True
        if time.time() > dl:
            return False
        cells = execution_cells(ctx)
        p.parent.mkdir(parents=True, exist_ok=True)
        pd.to_pickle(cells, p)
        return True
    raise ValueError(fam)


def execution_cells(ctx: dict) -> dict[str, pd.DataFrame]:
    from core import execution_lab as xl

    price = ctx["core_price"]
    w = cl.build_weights(price[0], price[1], cl.CoreConfig(cash="bil"))
    w = w[w.index >= pd.Timestamp(ctx["core_start"])]
    trades = xl.core_trades(w, cs.CORE_WEIGHT)
    data = ctx["sat_data"]()
    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    sched = sl.run_variant(spec, spec["signal"]["params_grid"][0], sl.load_signal(code), data)["schedule"]
    trades += xl.satellite_trades(sched, cs.SATELLITE_WEIGHT)
    frames = {t: df.sort_index() for t, df in ctx["core_hist"].items()}
    frames.update({t: df.sort_index() for t, df in data.ohlcv.items()})
    factors = {t: xl.adjusted(df).to_numpy(dtype=float) for t, df in frames.items()}
    rules = sp.execution_rules()
    cells: dict[str, dict] = {}
    for tr in trades:
        df = frames.get(tr["ticker"])
        if df is None or tr["date"] not in df.index:
            continue
        i = df.index.get_loc(tr["date"])
        f = factors[tr["ticker"]]
        base = sp.execute_param(df, i, tr["side"], {"kind": "base"}, f)
        if base is None:
            continue
        row = {}
        for name, rule in rules:
            px = sp.execute_param(df, i, tr["side"], rule, f)
            row[name] = None if px is None else (base / px - 1 if tr["side"] == "buy" else px / base - 1)
        key = f"{tr['sleeve']}|{tr['side']}"
        cells.setdefault(key, []).append((tr["date"], tr["w"], row))
        if tr["sleeve"] == "satellite" and tr["side"] == "buy":
            end = tr.get("end") or df.index[-1]
            tp = {"base": 0.0}
            for lvl in sp.TAKE_PROFIT_LEVELS:
                tp[f"tp{int(lvl * 100)}%"] = xl.take_profit_improvement(df, tr["date"], end, lvl)
            cells.setdefault("satellite|hold_take_profit", []).append((tr["date"], tr["w"], tp))
    out = {}
    for key, rows in cells.items():
        recs = pd.DataFrame([{"date": d, "w": w, **r} for d, w, r in rows])
        cols = [c for c in recs.columns if c not in ("date", "w")]
        by = recs.groupby("date").apply(
            lambda g: pd.Series({c: np.average(g[c].astype(float).fillna(0.0), weights=g["w"]) for c in cols}), include_groups=False)
        out[key] = by
    return out


# ---------------------------------------------------------------- 마무리
def finalize(store: Store, ctx: dict, partial: bool) -> dict:
    results, verdicts = {}, {}
    for fam in FAMILIES:
        if fam == "F4_execution":
            p = store.root / fam / "cells.pkl"
            if not p.exists():
                continue
            split = ctx["core_idx"][-1] - pd.DateOffset(years=2)
            res = sp.finalize_execution_family(pd.read_pickle(p), split)
            results[fam] = res
            for k, v in res.items():
                verdicts[f"{fam}:{k}"] = v["verdict"]
            continue
        if fam == "F1_satellite":
            cfgs = sp.satellite_configs()
            names_all = [sp.satellite_config_name(c) for c in cfgs]
            data = ctx["sat_data"]()
            idx = ctx["sat_idx"](data)
            inc = sp.SATELLITE_INCUMBENT
        else:
            names_all = [n for n, _ in (sp.core_configs() if fam == "F2_core_select" else sp.core_exit_rules())]
            idx = ctx["core_idx"]
            inc = sp.CORE_INCUMBENT if fam == "F2_core_select" else "none"
        done = [(n, store.load(fam, i)) for i, n in enumerate(names_all) if store.has(fam, i)]
        done = [(n, a) for n, a in done if not np.all(np.isnan(a))]
        if not done or inc not in [n for n, _ in done]:
            continue
        names = [n for n, _ in done]
        mat = np.column_stack([a for _, a in done]).astype(float)
        split = idx[-1] - pd.DateOffset(years=2)
        res = sp.finalize_returns_family(names, mat, idx, split, inc)
        res["n_configs_planned"] = len(names_all)
        results[fam] = res
        verdicts[fam] = res["verdict"]
    return {"id": "sprint-2w", "judge_version": sp.JUDGE_VERSION, "partial": partial,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "verdicts": verdicts, "families": results}


FAM_LABEL = {"F1_satellite": "F1 새틀라이트 선정", "F2_core_select": "F2 코어 선정", "F3_core_exit": "F3 코어 보유 중 매도",
             "F4_execution": "F4 사고파는 가격"}


def report(p: dict, smoke: bool) -> str:
    def pct(x):
        return "—" if x is None else f"{x:.0%}"

    def num(x, d=2):
        return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}f}"

    L = ["# 2주 R&D 스프린트 결과", "", f"생성 {p['generated_at']}" + (" · 마감으로 일부 설정 미완료" if p["partial"] else "")
         + (" · **스모크(합성 데이터) — 실제 결과 아님**" if smoke else ""), "",
         "판정 sprint-judge/v1: 앞 구간 최선 → 시도 수 보정 DSR ≥ 0.95 → 과적합 확률 PBO ≤ 25% → 떼어 둔 2년에서 현 규칙보다 나음. "
         "모두 만족하면 CANDIDATE(사람 검토 후보), 아니면 KEEP_CURRENT(현 규칙 유지).", ""]
    for fam, r in p["families"].items():
        L.append(f"## {FAM_LABEL[fam]}")
        if fam == "F4_execution":
            L += ["", "| 칸 | 판정 | 앞 구간 최선 | 앞 구간 개선 | 떼어 둔 2년 | DSR | PBO | 사유 |", "|---|---|---|---|---|---|---|---|"]
            for k, v in r.items():
                L.append(f"| {k} | **{v['verdict']}** | {v['winner']} | {v['winner_is_bps']:+.1f}bp | "
                         f"{'—' if v['winner_oos_bps'] is None else f'{v['winner_oos_bps']:+.1f}bp'} | {v['dsr']:.2f} | "
                         f"{pct((v['pbo'] or {}).get('pbo'))} | {'; '.join(v['reasons']) or '—'} |")
            L.append("")
            continue
        L += ["", f"- 판정 **{r['verdict']}** · 설정 {r['n_configs']}/{r.get('n_configs_planned', r['n_configs'])}개 · 현 규칙 앞 구간 순위 {r['incumbent_is_rank']}위",
              f"- 앞 구간 최선: `{r['winner']}` (샤프 {num(r['winner_is'].get('sharpe'))}, 연 {pct(r['winner_is'].get('cagr'))}, 최대낙폭 {pct(r['winner_is'].get('mdd'))})",
              f"- 현 규칙: `{r['incumbent']}` (샤프 {num(r['incumbent_is'].get('sharpe'))}, 연 {pct(r['incumbent_is'].get('cagr'))}, 최대낙폭 {pct(r['incumbent_is'].get('mdd'))})",
              f"- DSR {r['dsr']:.2f} · 과적합 확률 PBO {pct((r['pbo'] or {}).get('pbo'))} · 떼어 둔 2년 샤프 승자 {num(r['winner_oos'].get('sharpe'))} vs 현 규칙 {num(r['incumbent_oos'].get('sharpe'))}",
              f"- 사유: {'; '.join(r['reasons']) or '—'}", "", "| 앞 구간 상위 | 앞 구간 샤프 | 떼어 둔 2년 샤프 |", "|---|---|---|"]
        for t in r["top10"]:
            L.append(f"| `{t['config']}` | {num(t['is'].get('sharpe'))} | {num(t['oos'].get('sharpe'))} |")
        L.append("")
    L += ["- 상위 목록의 떼어 둔 2년 숫자는 참고용이다(승자 선택에 쓰지 않았다). 과거 결과는 미래를 보장하지 않는다. CANDIDATE 도 엔진에 자동 반영되지 않는다."]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--out", required=True)
    a.add_argument("--checkpoint", required=True)
    a.add_argument("--smoke", action="store_true")
    args = a.parse_args(argv)
    out, store = Path(args.out), Store(Path(args.checkpoint))
    out.mkdir(parents=True, exist_ok=True)
    dl = deadline()
    hist, price, total = load_core(args.smoke)
    core_start = "2009-01-02" if args.smoke else CORE_START
    cache: dict = {}

    def sat_data():
        if "d" not in cache:
            cache["d"] = load_satellite(args.smoke, {"champion40", "sp500_pit"})
        return cache["d"]

    def sat_idx(data):
        common = "2010-08-01"
        return data.trading_days[data.trading_days >= pd.Timestamp(common)]

    bil_tr = total[1][cs.CORE_CASH_ETF] if cs.CORE_CASH_ETF in total[1].columns else None
    cash_r = bil_tr.pct_change(fill_method=None).fillna(0.0) if bil_tr is not None else pd.Series(0.0, index=total[0].index)
    ctx = {"core_hist": hist, "core_price": price, "core_total": total, "core_start": core_start, "cash_r": cash_r,
           "core_idx": price[0].index[price[0].index >= pd.Timestamp(core_start)], "sat_data": sat_data, "sat_idx": sat_idx}
    meta = store.meta()
    past_end = datetime.now(KST) > SPRINT_END
    all_done = True
    for fam in FAMILIES:
        if past_end:
            all_done = False
            break
        log(f"{fam} 계산")
        ok = run_family(fam, store, ctx, dl, args.smoke)
        if not ok:
            log(f"{fam}: 시간 예산 소진 — 다음 창에 이어서")
            return EXIT_IN_PROGRESS
        if fam not in meta["notified"]:
            meta["notified"].append(fam)
            store.save_meta(meta)
            notify(f"[R&D 스프린트] {FAM_LABEL[fam]} 계산 완료 — 판정은 네 가족이 모두 끝난 뒤 한 번에 합니다.", args.smoke)
    payload = finalize(store, ctx, partial=not all_done)
    (out / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(report(payload, args.smoke), encoding="utf-8")
    log(f"판정 {payload['verdicts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
