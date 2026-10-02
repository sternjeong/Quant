"""검증 연구 tech-rnd-v1: 유튜브 대본 출신 차트 매매 규칙 — 단독 성과, 한계 돌파, 챔피언과의 시너지. (사전 등록, 2026-10-02)

## 사전 등록 (결과를 보기 전에 고정 — 바꾸려면 새 id)
데이터 3분할: 개발(2010-08 ~ 2019-12) / 검증(2020-01 ~ 떼어 둔 구간 직전) / 떼어 둔 마지막 2년(최종 판정에서 한 번만).
R1 탐색: core/technical_lab.rule_grid() 34개 × 풀(champion40, sp500_pit) × 최대 보유 K(5, 10, 20) = 204개, 단독 슬리브.
R2 한계 돌파: R1 에서 개발 구간 샤프 상위 중 검증 구간 샤프가 같은 풀 '그냥 사서 들고 있기'보다 높은 것 최대 10개
   (하나도 없으면 개발 구간 상위 5개). 각각에 9가지 변형: 국면 게이트 4(강세장만·약세장만·고변동(VIX>20)만·저변동만),
   종목 추세 필터 1(종가 > 200일선일 때만), 회전율 줄이기 2(청산 4일 지연·주 1회 결정), K 이웃 2(×0.5, ×2).
R3 시너지: R1+R2 중 개발 구간 샤프 > 0 인 것에서 검증 구간 샤프 상위 3개 슬리브 × 결합 5가지
   (새틀라이트 대신 15% / 새틀라이트 7.5+규칙 7.5 / 코어 75+새틀라이트 15+규칙 10 / 약세장에만 새틀라이트→규칙 / 고변동에만 새틀라이트→규칙)
   + 현 새틀라이트에 종목 게이트 3가지(50일선 위·200일선 위·볼린저 중심선 위일 때만 보유). 비교 대상 = 현 챔피언(코어 85 + 새틀라이트 15).
판정 tech-judge/v1 (가족: 단독=R1+R2, 결합=R3):
  1) 승자 = 개발+검증(IS) 샤프 최고 2) 승자의 비교 대상 대비 초과의 DSR ≥ 0.95 — 시도 수 = 이 연구 전체 설정 수(R1+R2+R3),
  3) CSCV PBO ≤ 25%, 4) 떼어 둔 2년(한 번만) 샤프 > 비교 대상. 모두 만족 = CANDIDATE(사람 검토), 아니면 KEEP_CURRENT.
  비교 대상: 단독 가족은 현 새틀라이트 규칙(같은 15% 슬리브 역할), 결합 가족은 현 챔피언.
진단(판정과 무관, 보고용): 국면별 초과수익·상관(언제 시너지가 나는가), 손익분기 비용, 규칙 종류별 최고.
비용 편도 8bp, 남는 몫 BIL. 한계: 일봉, 상장폐지 결측, 세금 미반영, 같은 날 종가 결정·다음 날 체결.
샤프·DSR·PBO 는 모두 단기국채(BIL) 대비 초과수익으로 계산한다 — 거의 매매하지 않아 단기국채에만 있는 규칙이 변동성 0 으로
샤프가 터무니없이 커지는 문제를 스모크에서 발견해 실제 데이터를 돌리기 전에 고정(2026-10-02).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
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
from core import technical_lab as tl  # noqa: E402

POOLS = ("champion40", "sp500_pit")
KS = (5, 10, 20)
COMMON = "2010-08-01"
EXIT_IN_PROGRESS = 3


def log(m):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {m}", flush=True)


def deadline() -> float:
    raw = os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH")
    return (float(raw) if raw else time.time() + 3 * 3600) - 120


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def p(self, key: str) -> Path:
        return self.root / (key.replace("/", "_").replace("|", "__").replace(":", "_").replace("<", "lt").replace(">", "gt") + ".npy")

    def has(self, key):
        return self.p(key).exists()

    def save(self, key, arr):
        tmp = self.p(key).with_suffix(".tmp.npy")
        np.save(tmp, np.asarray(arr, dtype=np.float32))
        os.replace(tmp, self.p(key))

    def load(self, key):
        return np.load(self.p(key)).astype(float)

    def json(self, name, obj=None):
        f = self.root / f"{name}.json"
        if obj is None:
            return json.loads(f.read_text()) if f.exists() else None
        f.write_text(json.dumps(obj, ensure_ascii=False, default=str))


# ---------------------------------------------------------------- 데이터·기준선
def load_all(smoke: bool):
    if smoke:
        pp, poolp = sl.synthetic_providers(n_tickers=30, start="2006-01-01", end="2016-12-30")
        data = sl.build_data(set(POOLS), start="2008-01-01", end="2016-12-30", pool_provider=poolp, price_provider=pp)
        for t, df in data.ohlcv.items():
            rng = np.random.default_rng(abs(hash(t)) % 1000)
            df["Volume"] = 1e6 * np.exp(rng.normal(0, 0.5, len(df)))
            df["Adj Close"] = df["Close"]
        idx = data.trading_days
        spy = pp("SPY", "2006-01-01", "2017-01-01")["Close"]
        vix = pd.Series(18 + 6 * np.sin(np.arange(len(idx)) / 40.0), index=idx)
        bil = pd.Series(0.0001, index=idx)
        core = pd.Series(np.random.default_rng(1).normal(0.0003, 0.008, len(idx)), index=idx)
        return data, spy, vix, bil, core
    data = sl.build_data(set(POOLS), start="2008-01-01", log=log)
    from core.market_data import get_price_history

    spy = get_price_history("SPY", start="2007-01-01", interval="1d")["Close"]
    vix = get_price_history("^VIX", start="2007-01-01", interval="1d")["Close"]
    b = get_price_history("BIL", start="2007-01-01", interval="1d")
    bil = (b["Adj Close"] if "Adj Close" in b else b["Close"]).pct_change(fill_method=None)
    sys.path.insert(0, str(PROJECT_ROOT / "research/jobs/sprint-2w"))
    hist, price, total = _load_core()
    core = cl.run(price[0], price[1], cl.CoreConfig(cash="bil"), "2008-01-01", total=total)
    return data, spy, vix, bil, core


def _load_core():
    tickers = list(cs.CORE_UNIVERSE) + [cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF]
    from core.market_data import get_multiple_price_history

    hist = get_multiple_price_history(tickers, start="2006-01-01", end=None, interval="1d")
    names = [t for t in tickers if t in hist and not hist[t].empty]
    price = cs._closes_from_histories(hist, names)
    total = cs._closes_from_histories(hist, names, field=cs.CORE_PRICE_FIELD)
    core = [t for t in cs.CORE_UNIVERSE if t in names]
    ex = [t for t in (cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF) if t in names]
    return hist, (price[core], price[ex]), (total[core], total[ex])


# ---------------------------------------------------------------- 실행
def main(argv=None) -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--out", required=True)
    a.add_argument("--checkpoint", required=True)
    a.add_argument("--smoke", action="store_true")
    args = a.parse_args(argv)
    out, st = Path(args.out), Store(Path(args.checkpoint))
    out.mkdir(parents=True, exist_ok=True)
    dl = deadline()
    data, spy, vix, bil, core_r = load_all(args.smoke)
    days = data.trading_days[data.trading_days >= pd.Timestamp("2011-01-03" if args.smoke else COMMON)]
    split = days[-1] - pd.DateOffset(years=2)
    train_end = pd.Timestamp("2014-01-01") if args.smoke else tl.TRAIN_END
    tickers = sorted(data.ohlcv)
    rets = tl.adj_returns(data, days, tickers)
    cash = bil.reindex(days).fillna(0.0)
    members = {pt: tl.membership(data, pt, days) for pt in POOLS}
    reg = tl.regimes(spy, vix, days)
    core_r = core_r.reindex(days).fillna(0.0)

    # 현 새틀라이트(같은 포지션 엔진) — 결합 비교를 같은 엔진으로 하기 위해
    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    sched = sl.run_variant(spec, spec["signal"]["params_grid"][0], sl.load_signal(code), data)["schedule"]
    sat_pos = pd.DataFrame(0.0, index=days, columns=tickers)
    for i, (d, picks) in enumerate(sched):
        d0 = pd.Timestamp(d)
        d1 = pd.Timestamp(sched[i + 1][0]) if i + 1 < len(sched) else days[-1] + pd.Timedelta(days=1)
        rows = (days >= d0) & (days < d1)
        for t in picks:
            if t in sat_pos.columns:
                sat_pos.loc[rows, t] = 1.0
    all_member = pd.DataFrame(True, index=days, columns=tickers)
    # 이하 모든 수익은 단기국채(BIL) 대비 초과수익(샤프·DSR·PBO 를 초과수익으로 재기 위해)
    core_r = core_r - cash
    sat_r = tl.sleeve_returns(sat_pos, all_member, rets, 3, cash) - cash
    champion = 0.85 * core_r + 0.15 * sat_r
    bh = {pt: tl.sleeve_returns(pd.DataFrame(1.0, index=days, columns=tickers), members[pt], rets, 1, cash) - cash for pt in POOLS}

    is_mask = days < split
    tr_mask = days < train_end
    va_mask = (days >= train_end) & is_mask

    def sh(r, mask):
        return tl.stats(pd.Series(r, index=days)[mask]).get("sharpe", float("nan"))

    # ---- R1 ----
    pos_cache: dict = {}
    r1 = []
    for name, kind, p in tl.rule_grid():
        for pt in POOLS:
            keys = [f"R1|{name}|{pt}|k{k}" for k in KS]
            if all(st.has(k) for k in keys):
                r1 += keys
                continue
            if time.time() > dl:
                log("시간 예산 소진(R1) — 다음 창에 이어서")
                return EXIT_IN_PROGRESS
            pos = positions(data, kind, p, days, tickers, pos_cache)
            for k, key in zip(KS, keys):
                st.save(key, (tl.sleeve_returns(pos, members[pt], rets, k, cash) - cash).to_numpy())
            be = tl.breakeven_bps(pos, members[pt], rets, 10, cash)
            meta = st.json("breakeven") or {}
            meta[f"{name}|{pt}"] = be
            st.json("breakeven", meta)
            r1 += keys
    log(f"R1 완료 {len(r1)}개")

    # ---- R2 (사전 등록 규칙으로 후보 선택) ----
    r1_stats = {k: (sh(st.load(k), tr_mask), sh(st.load(k), va_mask)) for k in r1}
    bh_va = {pt: sh(bh[pt].to_numpy(), va_mask) for pt in POOLS}
    ranked = sorted(r1, key=lambda k: -np.nan_to_num(r1_stats[k][0], nan=-9))
    passed = [k for k in ranked if r1_stats[k][1] > bh_va[k.split("|")[2]]]
    cands = passed[:10] if passed else ranked[:5]
    st.json("r2_candidates", {"candidates": cands, "rule": "검증 통과 상위 10" if passed else "통과 없음 → 개발 상위 5"})
    grid = {n: (kind, p) for n, kind, p in tl.rule_grid()}
    r2 = []
    for key in cands:
        _, name, pt, kk = key.split("|")
        k = int(kk[1:])
        kind, p = grid[name]
        variants = {"gate_bull": ("gate", "bull"), "gate_bear": ("gate", "bear"), "gate_high_vol": ("gate", "high_vol"),
                    "gate_low_vol": ("gate", "low_vol"), "trend200": ("trend", None), "min_hold5": ("turn", "min_hold5"),
                    "weekly": ("turn", "weekly"), "k_half": ("k", max(1, k // 2)), "k_double": ("k", k * 2)}
        for vn, (vt, vv) in variants.items():
            vkey = f"R2|{name}|{pt}|k{k}|{vn}"
            r2.append(vkey)
            if st.has(vkey):
                continue
            if time.time() > dl:
                log("시간 예산 소진(R2) — 다음 창에 이어서")
                return EXIT_IN_PROGRESS
            pos = positions(data, kind, p, days, tickers, pos_cache)
            gate, kk2 = None, k
            if vt == "gate":
                gate = reg[vv] if vv in reg else pd.Series(False, index=days)
                gate = gate.shift(0)  # 그날 종가 국면으로 그날 포지션 결정(수익은 다음 날부터)
            elif vt == "trend":
                trend = trend_mask(data, days, tickers, pos_cache)
                pos = pos * trend.reindex(columns=pos.columns).fillna(0.0)
            elif vt == "turn":
                pos = tl.turnover_reduce(pos, vv)
            elif vt == "k":
                kk2 = vv
            st.save(vkey, (tl.sleeve_returns(pos, members[pt], rets, kk2, cash, gate=gate) - cash).to_numpy())
    log(f"R2 완료 {len(r2)}개")

    # ---- R3 시너지 ----
    pool_keys = [k for k in r1 + r2 if sh(st.load(k), tr_mask) > 0]
    top3 = sorted(pool_keys, key=lambda k: -np.nan_to_num(sh(st.load(k), va_mask), nan=-9))[:3]
    st.json("r3_sleeves", top3)
    r3 = {}
    bear = reg["bear"].shift(1).fillna(False).astype(bool)
    hv = reg["high_vol"].shift(1).fillna(False).astype(bool) if "high_vol" in reg else pd.Series(False, index=days)
    for key in top3:
        tech = pd.Series(st.load(key), index=days)
        r3[f"R3|replace_sat|{key}"] = 0.85 * core_r + 0.15 * tech
        r3[f"R3|split_sat|{key}"] = 0.85 * core_r + 0.075 * sat_r + 0.075 * tech
        r3[f"R3|add_tech10|{key}"] = 0.75 * core_r + 0.15 * sat_r + 0.10 * tech
        r3[f"R3|bear_switch|{key}"] = 0.85 * core_r + 0.15 * sat_r.where(~bear, tech)
        r3[f"R3|highvol_switch|{key}"] = 0.85 * core_r + 0.15 * sat_r.where(~hv, tech)
    for gname, n in (("sat_gate_sma50", 50), ("sat_gate_sma200", 200), ("sat_gate_bbmid", 20)):
        g = gate_matrix(data, days, tickers, n)
        r3[f"R3|{gname}"] = 0.85 * core_r + 0.15 * (tl.sleeve_returns(sat_pos * g.reindex(columns=sat_pos.columns).fillna(0.0), all_member, rets, 3, cash) - cash)
    log(f"R3 완료 {len(r3)}개")

    # ---- 판정 ----
    n_total = len(r1) + len(r2) + len(r3)
    standalone = {k: st.load(k) for k in r1 + r2}
    fam_s = judge_family(standalone, sat_r.to_numpy(), days, split, n_total, "현 새틀라이트(같은 엔진, 15% 슬리브)")
    fam_c = judge_family({k: v.to_numpy() for k, v in r3.items()}, champion.to_numpy(), days, split, n_total, "현 챔피언(코어 85 + 새틀라이트 15)")
    # 진단
    be = st.json("breakeven") or {}
    diag_top = []
    for k in sorted(standalone, key=lambda k: -np.nan_to_num(sh(standalone[k], is_mask), nan=-9))[:15]:
        parts = k.split("|")
        r = pd.Series(standalone[k], index=days)
        diag_top.append({"config": k, "train": sh(standalone[k], tr_mask), "val": sh(standalone[k], va_mask),
                         "corr_champion": float(r[is_mask].corr(champion[is_mask])),
                         "breakeven_bps": be.get(f"{parts[1]}|{parts[2]}"),
                         "regimes_vs_satellite": tl.regime_table(r[is_mask], sat_r[is_mask], reg[is_mask])})
    kinds = {}
    for name, kind, _ in tl.rule_grid():
        best = max((k for k in r1 if k.split("|")[1] == name), key=lambda k: np.nan_to_num(sh(standalone[k], is_mask), nan=-9))
        kinds.setdefault(kind, []).append((sh(standalone[best], is_mask), best))
    kinds = {kd: max(v)[1] for kd, v in kinds.items()}
    synergy_regimes = {k: tl.regime_table(r[is_mask] if isinstance(r, pd.Series) else pd.Series(r, index=days)[is_mask],
                                          champion[is_mask], reg[is_mask]) for k, r in list(r3.items())[:20]}
    payload = {"id": "tech-rnd-v1", "smoke": args.smoke, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "split": str(split.date()), "train_end": str(train_end.date()), "n_trials_total": n_total,
               "counts": {"R1": len(r1), "R2": len(r2), "R3": len(r3)},
               "benchmarks": {"satellite_is": tl.stats(sat_r[is_mask]), "champion_is": tl.stats(champion[is_mask]),
                              **{f"buyhold_{pt}_is": tl.stats(bh[pt][is_mask]) for pt in POOLS}},
               "r2_candidates": st.json("r2_candidates"), "r3_sleeves": top3,
               "verdicts": {"standalone": fam_s["verdict"], "synergy": fam_c["verdict"]},
               "families": {"standalone": fam_s, "synergy": fam_c},
               "diagnostics": {"top15": diag_top, "best_by_kind": kinds, "synergy_regimes": synergy_regimes}}
    (out / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(report(payload), encoding="utf-8")
    log(f"판정 {payload['verdicts']}")
    return 0


def positions(data, kind, p, days, tickers, cache):
    key = (kind, json.dumps(p, sort_keys=True))
    if key not in cache:
        cache.clear()  # 메모리 보호: 최근 하나만
        cache[key] = tl.positions_matrix(data, kind, p, days, tickers)
    return cache[key]


def trend_mask(data, days, tickers, cache):
    if "__trend" not in cache:
        cache["__trend"] = gate_matrix(data, days, tickers, 200)
    return cache["__trend"]


def gate_matrix(data, days, tickers, n):
    cols = {}
    for t in tickers:
        df = data.ohlcv.get(t)
        if df is None:
            continue
        c = df["Close"]
        cols[t] = (c > c.rolling(n).mean()).astype(float).reindex(days).ffill().fillna(0.0)
    return pd.DataFrame(cols, index=days).fillna(0.0)


def judge_family(configs: dict[str, np.ndarray], bench: np.ndarray, days, split, n_total: int, bench_name: str) -> dict:
    names = ["__bench__"] + list(configs)
    mat = np.column_stack([bench] + [configs[k] for k in configs])
    res = sp.finalize_returns_family(names, mat, days, split, "__bench__")
    # 시도 수는 이 연구 전체(R1+R2+R3)로 다시 계산 — finalize 는 가족 크기만 안다
    is_mask = np.asarray(days < split)
    win = names.index(res["winner"])
    active = mat[is_mask, win] - mat[is_mask, 0]
    mo = sp.moments(active)
    act_srs = list(sp.sharpe_cols(mat[is_mask] - mat[is_mask][:, [0]]))[1:]
    dsr = sp.deflated(mo["sr"], mo["n"], mo["skew"], mo["kurt"], n_total, act_srs)
    res["dsr"] = round(dsr["dsr"], 4)
    res["n_trials_total"] = n_total
    res["benchmark"] = bench_name
    reasons = [r for r in res["reasons"] if not r.startswith("DSR")]
    if res["winner"] == "__bench__":
        reasons = ["앞 구간 최선이 비교 대상 자신"] + reasons
    if dsr["dsr"] < sp.DSR_MIN:
        reasons.append(f"DSR {dsr['dsr']:.2f} < {sp.DSR_MIN} (이 연구 전체 시도 {n_total})")
    res["reasons"] = list(dict.fromkeys(reasons))
    res["verdict"] = "CANDIDATE" if not res["reasons"] else "KEEP_CURRENT"
    return res


def report(p: dict) -> str:
    def num(x, d=2):
        return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}f}"

    def pct(x):
        return "—" if x is None else f"{x:.0%}"

    b = p["benchmarks"]
    L = ["# 차트 매매 규칙(유튜브 대본 출신) R&D v1", "",
         f"생성 {p['generated_at']} · 개발 ~{p['train_end']} · 검증 ~{p['split']} · 그 뒤 2년 떼어 둠 · 전체 시도 {p['n_trials_total']}개 "
         f"(R1 {p['counts']['R1']}, R2 {p['counts']['R2']}, R3 {p['counts']['R3']})" + (" · **스모크(합성 데이터) — 실제 결과 아님**" if p["smoke"] else ""), "",
         "샤프는 모두 단기국채(BIL) 대비 초과수익 기준. 비교 기준(개발+검증 구간): "
         f"현 새틀라이트 샤프 {num(b['satellite_is'].get('sharpe'))}, 현 챔피언 샤프 {num(b['champion_is'].get('sharpe'))}, "
         f"그냥 사서 들고 있기(champion40) {num(b['buyhold_champion40_is'].get('sharpe'))}, (S&P500 PIT) {num(b['buyhold_sp500_pit_is'].get('sharpe'))}", ""]
    for fam, label in (("standalone", "단독 슬리브(R1+R2) — 새틀라이트 대신 쓸 만한가"), ("synergy", "챔피언과 결합(R3) — 시너지가 있는가")):
        r = p["families"][fam]
        L += [f"## {label}", "", f"- 판정 **{r['verdict']}** · 앞 구간 최선 `{r['winner']}` · 비교 대상 {r['benchmark']}",
              f"- 앞 구간 샤프 승자 {num(r['winner_is'].get('sharpe'))} vs 비교 대상 {num(r['incumbent_is'].get('sharpe'))} · "
              f"DSR {num(r['dsr'])} · 과적합 확률 PBO {pct((r['pbo'] or {}).get('pbo'))} · 떼어 둔 2년 샤프 승자 {num(r['winner_oos'].get('sharpe'))} vs {num(r['incumbent_oos'].get('sharpe'))}",
              f"- 사유: {'; '.join(r['reasons']) or '—'}", "", "| 앞 구간 상위 | 앞 구간 샤프 | 최대낙폭 | 떼어 둔 2년 샤프 |", "|---|---|---|---|"]
        for t in r["top10"]:
            L.append(f"| `{t['config']}` | {num(t['is'].get('sharpe'))} | {pct(t['is'].get('mdd'))} | {num(t['oos'].get('sharpe'))} |")
        L.append("")
    d = p["diagnostics"]
    L += ["## 진단 — 한계와 시너지가 나는 국면 (판정과 무관, 보고용)", "",
          "| 단독 상위 | 개발 샤프 | 검증 샤프 | 챔피언과 상관 | 손익분기 비용(편도) | 약세장 초과(vs 새틀라이트) | 고변동 초과 |", "|---|---|---|---|---|---|---|"]
    for t in d["top15"]:
        rg = t["regimes_vs_satellite"]
        L.append(f"| `{t['config']}` | {num(t['train'])} | {num(t['val'])} | {num(t['corr_champion'])} | "
                 f"{'—' if t['breakeven_bps'] is None else f'{t['breakeven_bps']:.0f}bp'} | "
                 f"{pct((rg.get('bear') or {}).get('excess_ann'))} | {pct((rg.get('high_vol') or {}).get('excess_ann'))} |")
    L += ["", "규칙 종류별 최고: " + ", ".join(f"{k} → `{v}`" for k, v in d["best_by_kind"].items()), "",
          "- 손익분기 비용이 8bp 근처거나 그보다 낮으면 회전율이 수익을 다 잡아먹는 규칙이다.",
          "- 국면별 초과는 '언제 시너지가 나는가'를 보는 진단이며, 국면 게이트 변형(R2)·국면 전환 결합(R3)이 그 가설을 실제로 시험한다.",
          "- CANDIDATE 도 엔진에 자동 반영되지 않는다. 과거 결과는 미래를 보장하지 않는다."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
