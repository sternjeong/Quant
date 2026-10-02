"""검증 연구 info-rnd-v1 — docs/HYPOTHESIS_CATALOG.md 의 '바로 시험 가능' 가설 1차. (사전 등록, 2026-10-02)

## 사전 등록 (결과를 보기 전에 고정 — 바꾸려면 새 id)
A 가족(코어 급락 필터, 2008-01~, 비교 대상 = 현 코어: 월간 SPY 200일선 + 남는 몫 BIL):
  매일 전날 종가로 판단해 코어 위험자산을 줄이고 줄인 몫은 BIL(그날 종가 체결 — 엔진 관례).
  A1 VIX/VIX3M > {1.00, 1.05, 1.10} → 위험자산 ×{0.5, 0} (6)
  A2 VIX > {25, 30, 35} 이고 SPY < 50일선 → ×0.5 (3)
  A3 SPY 20일 실현변동성 > 직전 252일 분포의 {90, 95} 백분위 → ×0.5 (2)
  A4 월간 200일선 필터를 빼고 A1(×0.5, {1.00, 1.05})만 (2)
B 가족(코인, 2015-07~, 비교 대상 = 현 챔피언: 코어 85 + 새틀라이트 15):
  B1 BTC-USD 를 코어 순위 후보 18번째 자산으로 (1)
  B2 코인 추세 슬리브: {BTC, BTC+ETH} × 신호 {EMA50, EMA100, EMA200 위, EMA20/50/100 중 2개 이상 위} × 비중 {2.5%, 5%}
     × 재원 {코어에서, 새틀라이트에서} (32). 신호 아래면 그 몫은 BIL. 편도 8bp.
  B3 비트코인 그냥 보유 {2.5%, 5%} × {코어에서, 새틀라이트에서} (4)
판정 = sprint-judge/v1 와 같은 규칙(core/sprint_lab.finalize_returns_family): 앞 구간 최선 → DSR ≥ 0.95(시도 수 = 가족 크기) →
  CSCV PBO ≤ 25% → 떼어 둔 마지막 2년 샤프 > 비교 대상. 샤프는 모두 BIL 대비 초과수익. CANDIDATE 도 엔진 자동 반영 없음.
D2(보고만): 코어 ETF 의 밤사이(전날 종가→시가) vs 장중(시가→종가) 연환산 수익.
FOMC 발표 전 상승(D1)은 정확한 과거 회의 날짜 목록이 필요해 이번에서 뺀다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import champion_strategy as cs  # noqa: E402
from core import core_lab as cl  # noqa: E402
from core import satellite_lab as sl  # noqa: E402
from core import sprint_lab as sp  # noqa: E402

CORE_START, CRYPTO_START = "2008-01-01", "2015-07-01"
EXTRA = ["^VIX", "^VIX3M", "BTC-USD", "ETH-USD"]
COST_BPS = 8.0


def load(smoke: bool):
    stock = list(cs.CORE_UNIVERSE) + [cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF]
    if smoke:
        idx = pd.bdate_range("2006-01-02", "2016-12-30")
        rng = np.random.default_rng(6)
        hist = {}
        for t in stock + EXTRA:
            c = 50 * np.exp(np.cumsum(rng.normal(0.0003, 0.02 if "USD" in t else 0.011, len(idx))))
            if t == "^VIX":
                c = 18 + 8 * np.abs(np.sin(np.arange(len(idx)) / 30.0))
            if t == "^VIX3M":
                c = np.full(len(idx), 20.0)
            hist[t] = pd.DataFrame({"Open": c * 0.999, "High": c, "Low": c, "Close": c, "Adj Close": c, "Volume": 1e6}, index=idx)
    else:
        from core.market_data import get_multiple_price_history

        hist = get_multiple_price_history(stock + EXTRA, start="2006-01-01", end=None, interval="1d")
    names = [t for t in stock if t in hist and not hist[t].empty]
    price = cs._closes_from_histories(hist, names)
    total = cs._closes_from_histories(hist, names, field=cs.CORE_PRICE_FIELD)
    days = price.index

    def series(t, field="Close"):
        df = hist.get(t)
        if df is None or df.empty:
            return pd.Series(np.nan, index=days)
        col = field if field in df.columns else "Close"
        return df[col].reindex(days.union(df.index)).ffill().reindex(days)

    ext = {t: series(t) for t in EXTRA}
    ext_tr = {t: series(t, "Adj Close") for t in ("BTC-USD", "ETH-USD")}
    return hist, price, total, ext, ext_tr


def gate_weights(w: pd.DataFrame, mult: pd.Series, cash: str = cs.CORE_CASH_ETF) -> pd.DataFrame:
    """위험자산 비중 × mult(그날 행), 줄인 몫은 BIL."""
    risky = [c for c in w.columns if c != cash]
    m = mult.reindex(w.index).fillna(1.0)
    out = w.copy()
    cut = out[risky].mul(1 - m, axis=0).sum(axis=1)
    out[risky] = out[risky].mul(m, axis=0)
    if cash in out.columns:
        out[cash] = out[cash] + cut
    return out


def main(argv=None) -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--out", required=True)
    a.add_argument("--checkpoint", required=True)
    a.add_argument("--smoke", action="store_true")
    args = a.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    hist, price, total, ext, ext_tr = load(args.smoke)
    core_cols = [t for t in cs.CORE_UNIVERSE if t in price.columns] + [cs.CORE_CASH_ETF]
    ex_cols = [cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF]
    start = "2009-01-02" if args.smoke else CORE_START
    cstart = "2012-07-02" if args.smoke else CRYPTO_START
    pc, pe, tc, te = price[[c for c in core_cols if c != cs.CORE_CASH_ETF]], price[ex_cols], total[[c for c in core_cols if c != cs.CORE_CASH_ETF]], total[ex_cols]
    cash_r = total[cs.CORE_CASH_ETF].pct_change(fill_method=None).fillna(0.0)
    spy = price[cs.MARKET_FILTER_TICKER]

    def run_w(w: pd.DataFrame, st: str) -> pd.Series:
        keep = tc.index >= pd.Timestamp(st)
        r = cl.portfolio_returns(tc[keep], te[keep], w.reindex(tc.index).fillna(0.0)[keep])
        return r - cash_r[keep]

    base_w = cl.build_weights(pc, pe, cl.CoreConfig(cash="bil"))
    nofilter_w = cl.build_weights(pc, pe, cl.CoreConfig(cash="bil", market_filter="none"))
    ratio = (ext["^VIX"] / ext["^VIX3M"]).shift(1)
    vix = ext["^VIX"].shift(1)
    below50 = (spy < spy.rolling(50).mean()).shift(1).fillna(False)
    rv = spy.pct_change(fill_method=None).rolling(20).std()
    A: dict[str, pd.Series] = {"A0_current": run_w(base_w, start)}
    for thr in (1.00, 1.05, 1.10):
        for cut in (0.5, 0.0):
            A[f"A1_vixts>{thr:.2f}_x{cut}"] = run_w(gate_weights(base_w, pd.Series(np.where(ratio > thr, cut, 1.0), index=ratio.index)), start)
    for lv in (25, 30, 35):
        A[f"A2_vix>{lv}&spy<sma50_x0.5"] = run_w(gate_weights(base_w, pd.Series(np.where((vix > lv) & below50, 0.5, 1.0), index=vix.index)), start)
    for q in (0.90, 0.95):
        hi = (rv > rv.rolling(252, min_periods=126).quantile(q)).shift(1).fillna(False)
        A[f"A3_rv20>p{int(q * 100)}_x0.5"] = run_w(gate_weights(base_w, pd.Series(np.where(hi, 0.5, 1.0), index=rv.index)), start)
    for thr in (1.00, 1.05):
        A[f"A4_no200dma+vixts>{thr:.2f}_x0.5"] = run_w(gate_weights(nofilter_w, pd.Series(np.where(ratio > thr, 0.5, 1.0), index=ratio.index)), start)

    # ---- B: 코인 ----
    if args.smoke:
        pp, poolp = sl.synthetic_providers(n_tickers=30, start="2006-01-01", end="2016-12-30")
        data = sl.build_data({"champion40"}, start="2010-01-01", end="2016-12-30", pool_provider=poolp, price_provider=pp)
    else:
        data = sl.build_data({"champion40"}, start="2010-01-01")
    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    sat = sl.run_variant(spec, spec["signal"]["params_grid"][0], sl.load_signal(code), data)["returns"]
    cidx = tc.index[tc.index >= pd.Timestamp(cstart)]
    sat = sat.reindex(cidx).fillna(0.0) - cash_r.reindex(cidx).fillna(0.0)  # 새틀라이트 남는 몫은 수익 0 → BIL 대비 초과
    core_ex = A["A0_current"].reindex(cidx).fillna(0.0)
    champ = 0.85 * core_ex + 0.15 * sat
    B: dict[str, pd.Series] = {"B0_current_champion": champ}
    # B1 비트코인 18번째 자산
    pc_b = pc.copy()
    pc_b["BTC-USD"] = ext["BTC-USD"]
    tc_b = tc.copy()
    tc_b["BTC-USD"] = ext_tr["BTC-USD"]
    wb = cl.build_weights(pc_b, pe, cl.CoreConfig(cash="bil", extra_assets=("BTC-USD",)))
    keep = tc_b.index >= pd.Timestamp(cstart)
    rb = cl.portfolio_returns(tc_b[keep], te[keep], wb.reindex(tc_b.index).fillna(0.0)[keep]) - cash_r[keep]
    B["B1_btc_as_core_asset"] = 0.85 * rb.reindex(cidx).fillna(0.0) + 0.15 * sat
    # B2·B3 코인 슬리브
    crypto_ret = {t: ext_tr[t].pct_change(fill_method=None).reindex(cidx).fillna(0.0) for t in ("BTC-USD", "ETH-USD")}
    def sig(t, kind):
        c = ext[t]
        if kind == "multi":
            votes = sum((c > c.ewm(span=n, adjust=False).mean()).astype(int) for n in (20, 50, 100))
            on = votes >= 2
        else:
            n = int(kind[3:])
            on = c > c.ewm(span=n, adjust=False).mean()
        return on.where(c.notna(), False).astype(float).reindex(cidx).fillna(0.0)
    def sleeve(assets, kind):
        pos = pd.DataFrame({t: (sig(t, kind) if kind != "hold" else ext[t].notna().astype(float).reindex(cidx).fillna(0.0)) for t in assets})
        avail = pd.DataFrame({t: ext[t].notna().reindex(cidx).fillna(False).astype(float) for t in assets})
        w = pos.div(avail.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
        ex = w.shift(1).fillna(0.0)
        gross = sum(ex[t] * crypto_ret[t] for t in assets) + (1 - ex.sum(axis=1)) * cash_r.reindex(cidx).fillna(0.0)
        turn = (ex - ex.shift(1).fillna(0.0)).abs().sum(axis=1)
        return gross - turn * COST_BPS / 1e4 - cash_r.reindex(cidx).fillna(0.0)
    for assets_name, assets in (("btc", ["BTC-USD"]), ("btc+eth", ["BTC-USD", "ETH-USD"])):
        for kind in ("ema50", "ema100", "ema200", "multi"):
            s = sleeve(assets, kind)
            for w in (0.025, 0.05):
                B[f"B2_{assets_name}_{kind}_{w:.3f}_from_core"] = (0.85 - w) * core_ex + 0.15 * sat + w * s
                B[f"B2_{assets_name}_{kind}_{w:.3f}_from_sat"] = 0.85 * core_ex + (0.15 - w) * sat + w * s
    hold = sleeve(["BTC-USD"], "hold")
    for w in (0.025, 0.05):
        B[f"B3_btc_hold_{w:.3f}_from_core"] = (0.85 - w) * core_ex + 0.15 * sat + w * hold
        B[f"B3_btc_hold_{w:.3f}_from_sat"] = 0.85 * core_ex + (0.15 - w) * sat + w * hold

    results = {}
    for fam, d, inc in (("A_crash_filters", A, "A0_current"), ("B_crypto", B, "B0_current_champion")):
        idx = next(iter(d.values())).index
        names = list(d)
        mat = np.column_stack([d[n].reindex(idx).fillna(0.0).to_numpy() for n in names])
        results[fam] = sp.finalize_returns_family(names, mat, idx, idx[-1] - pd.DateOffset(years=2), inc)
    # 진단: A 위기 구간별 초과(연 단위 합)
    crises = {"2008 금융위기": ("2008-09-01", "2009-03-31"), "2011 유럽위기": ("2011-07-01", "2011-10-31"),
              "2015-16 조정": ("2015-08-01", "2016-02-29"), "2018 4분기": ("2018-10-01", "2018-12-31"),
              "2020 코로나": ("2020-02-15", "2020-04-30"), "2022 긴축": ("2022-01-01", "2022-10-31"), "2025 관세 급락": ("2025-03-01", "2025-05-31")}
    crisis_tbl = {}
    for n in A:
        if n == "A0_current":
            continue
        row = {}
        for cname, (s0, s1) in crises.items():
            m = (A[n].index >= s0) & (A[n].index <= s1)
            if m.sum() > 5:
                row[cname] = float(((1 + A[n][m]).prod() - (1 + A["A0_current"][m]).prod()))
        crisis_tbl[n] = row
    # D2
    d2 = {}
    for t in [c for c in cs.CORE_UNIVERSE if c in hist]:
        df = hist[t]
        df = df[df.index >= pd.Timestamp(start)]
        on = (df["Open"] / df["Close"].shift(1) - 1).dropna()
        intra = (df["Close"] / df["Open"] - 1).dropna()
        d2[t] = {"overnight_ann": float(on.mean() * 252), "intraday_ann": float(intra.mean() * 252)}
    btc_corr = float(crypto_ret["BTC-USD"].corr(champ)) if crypto_ret["BTC-USD"].std() > 0 else None
    payload = {"id": "info-rnd-v1", "smoke": args.smoke, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "verdicts": {k: v["verdict"] for k, v in results.items()}, "families": results,
               "diagnostics": {"crisis_excess_vs_current": crisis_tbl, "overnight_vs_intraday": d2, "btc_corr_with_champion": btc_corr}}
    (out / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(report(payload), encoding="utf-8")
    print("판정", payload["verdicts"], flush=True)
    return 0


def report(p: dict) -> str:
    def num(x, d=2):
        return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}f}"

    def pct(x):
        return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:+.1%}"

    L = ["# 가설 카탈로그 1차(info-rnd-v1) — 빠른 급락 필터·코인", "", f"생성 {p['generated_at']}"
         + (" · **스모크(합성 데이터) — 실제 결과 아님**" if p["smoke"] else ""), "",
         "샤프는 단기국채(BIL) 대비 초과수익 기준. 판정: 앞 구간 최선 → DSR ≥ 0.95 → PBO ≤ 25% → 떼어 둔 2년에서 비교 대상보다 나음.", ""]
    labels = {"A_crash_filters": "A. 코어 급락 필터 (비교: 현 코어)", "B_crypto": "B. 코인 (비교: 현 챔피언)"}
    for fam, r in p["families"].items():
        L += [f"## {labels[fam]}", "", f"- 판정 **{r['verdict']}** · 앞 구간 최선 `{r['winner']}` · 현 규칙 앞 구간 순위 {r['incumbent_is_rank']}/{r['n_configs']}",
              f"- 앞 구간 샤프 {num(r['winner_is'].get('sharpe'))} vs 현 규칙 {num(r['incumbent_is'].get('sharpe'))}, 최대낙폭 {pct(r['winner_is'].get('mdd'))} vs {pct(r['incumbent_is'].get('mdd'))}",
              f"- DSR {num(r['dsr'])} · PBO {('—' if not r['pbo'] else f'{r['pbo']['pbo']:.0%}')} · 떼어 둔 2년 샤프 {num(r['winner_oos'].get('sharpe'))} vs {num(r['incumbent_oos'].get('sharpe'))}",
              f"- 사유: {'; '.join(r['reasons']) or '—'}", "", "| 앞 구간 상위 | 샤프 | 연수익 | 최대낙폭 | 떼어 둔 2년 샤프 |", "|---|---|---|---|---|"]
        for t in r["top10"]:
            L.append(f"| `{t['config']}` | {num(t['is'].get('sharpe'))} | {pct(t['is'].get('cagr'))} | {pct(t['is'].get('mdd'))} | {num(t['oos'].get('sharpe'))} |")
        L.append("")
    d = p["diagnostics"]
    crises = sorted({c for row in d["crisis_excess_vs_current"].values() for c in row})
    L += ["## 진단 — 위기 구간별 현 코어 대비 초과(누적, BIL 대비)", "", "| 필터 | " + " | ".join(crises) + " |", "|---|" + "---|" * len(crises)]
    for n, row in d["crisis_excess_vs_current"].items():
        L.append(f"| `{n}` | " + " | ".join(pct(row.get(c)) for c in crises) + " |")
    L += ["", "## 진단 — 밤사이 vs 장중 (코어 ETF, 연환산 평균)", "", "| ETF | 밤사이 | 장중 |", "|---|---|---|"]
    for t, v in d["overnight_vs_intraday"].items():
        L.append(f"| {t} | {pct(v['overnight_ann'])} | {pct(v['intraday_ann'])} |")
    L += ["", f"비트코인 일간 수익과 현 챔피언의 상관: {num(d['btc_corr_with_champion'])}", "",
          "- CANDIDATE 도 엔진에 자동 반영되지 않는다. 코인은 주말 움직임이 월요일 수익에 합쳐진다(주식 거래일 기준). 과거 결과는 미래를 보장하지 않는다."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
