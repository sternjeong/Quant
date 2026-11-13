"""frontier-tax-allowance-v1 — 끝없는 적립에서 연 250만 원 양도세 공제를 어디에 쓸까 (사전 등록 2026-11-14).

질문: 프런티어의 모든 수익이 '낙폭을 더 감수한 값'이고 알파는 아직 없다. 남은 자리는 세금이다.
팔지 않는 적립 계좌는 해마다 기본공제(250만 원)를 100% 버린다. 공제를 쓰는 길은 두 가지다.
  (ㄱ) 되돌림: 레버리지 다리를 공제 한도만큼만 팔아 시장을 산다 → 위험(베타 드리프트)을 공짜로 통제한다(= 지금 L20A, frontier-lev-rebal-v1 A4_ALLOW).
  (ㄴ) 원가 올리기: 시장 보유분을 공제 한도만큼 팔았다 **바로 되산다** → 자산 배분·시장 노출은 그대로이고 취득원가만 올라가
       청산 세금이 줄어든다(한국 해외주식 양도세에는 wash-sale 규정이 없다). 산술 상한 = 30년 × 250만 원 × 22% = 1,650만 원.
공제는 한 해에 하나뿐이라 (ㄱ)과 (ㄴ)은 **경쟁**한다. 순서를 정하면 둘 다 얻는가?
그리고 (ㄴ)은 레버리지가 없는 **SPY 그냥 보유 기준선에도 그대로 적용**되므로, 사실이면 프런티어의 기준선 자체가 올라간다.

새 메커니즘(세금 원가 올리기)을 재는 연구다 — 가격 신호·이동평균·손절률 격자를 키우지 않는다(가격 규칙은 한 줄도 없다).
판정 문턱·비교 대상·구간·계좌 모델은 아래 상수와 SPEC.md 에 결과를 보기 전에 고정했다.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "core" / "tax_fx.py").exists() and (p / "research" / "jobs").is_dir():
            return p
    raise RuntimeError("저장소 루트를 찾지 못했다")


PROJECT_ROOT = _find_root(Path(__file__).resolve())
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load(name: str, rel: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load("dca_lab", "research/jobs/dca-dip-deploy-v1/lab.py")  # 공용 실험실(Runner·부트스트랩·세금 상수)
from core import research_power as rp  # noqa: E402

# =================================================================================================
# 사전 등록 상수 (결과를 보기 전에 고정 — 이후 바꾸지 않는다)
# =================================================================================================
RULES_VERSION = "frontier-tax-allowance-v1/2026-11-14"

# 돈 (판정은 S1 만, 나머지는 보고만 — 공제는 정액이라 계좌가 커지면 효과가 묽어진다)
SCENARIOS = {"S1": (10_000_000.0, 150_000.0), "S2": (0.0, 100_000.0), "S3": (100_000_000.0, 1_000_000.0)}
JUDGE_SCENARIO = "S1"

BUY_COST = L.FEE + L.FX_SPREAD                    # 0.1% 수수료 + 0.05% 환전
SELL_COST = L.FEE + L.FX_SPREAD
CGT, ALLOWANCE = L.CGT, L.ALLOWANCE               # 22%, 연 250만 원
HARVEST_MONTH = 11                                # 12월(한국 연말 절세 매도 관행)

# 원가 올리기를 할 최소 평가이익률: 왕복 비용 0.3% ÷ 세율 22% ≈ 1.36% 가 손익분기 → 안전 여유를 둬 2%
MIN_GAIN_RATE = 0.02

# 다리 (필터 없음 — 가격 타이밍을 쓰지 않는다. l15f-robust-v1·lev-weight-frontier-v1 에서 w20 이 통과 칸)
TARGET_W = 0.20
MULT, FIN_SPREAD, LEG_FEE = 2.0, 0.010, 0.009

# 구간·가상 역사
HORIZON_MONTHS = 360                              # 30년 = '끝없음' 대리
DAYS_PER_MONTH, BLOCK_DAYS = 21, 63
N_PATHS, SEED = 2000, 20261114
ERAS = {"selection": ("1927-07-01", "1966-12-31"), "confirmation": ("1967-01-01", "2007-12-31")}
REPORT_ERAS = {"post2008": ("2008-01-01", "2100-01-01")}   # 이미 여러 연구가 본 구간 — 보고만

# 판정 문턱 — '위험 없는 이득'이라 크기보다 일관성을 본다
WIN_MIN, MED_MIN, P10_MIN = 0.90, 0.0005, 0.0     # 이긴 경로 ≥ 90%, 중앙 ≥ +0.05%p, 10분위 ≥ 0
MDD_GAP_MAX = 0.005                               # 쌍둥이 팔보다 낙폭이 0.5%p 넘게 나빠지면 탈락
LEG_W_MAX = 0.30                                  # 말기 다리 비중 중앙값 상한(드리프트 위험 통제)
MKT_MDD_GAP_MAX = 0.10                            # 프런티어 후보 자격: 시장 대비 낙폭 10%p 이내

ARMS = ["H0_MKT_STEPUP", "H1_LEG_NONE", "H2_LEG_REBAL", "H3_LEG_STEPUP", "H4_REBAL_FIRST", "H5_SPLIT"]
JUDGED = ["H0_MKT_STEPUP", "H2_LEG_REBAL", "H3_LEG_STEPUP", "H4_REBAL_FIRST", "H5_SPLIT"]
TWIN = {"H0_MKT_STEPUP": "MKT", "H2_LEG_REBAL": "H1_LEG_NONE", "H3_LEG_STEPUP": "H1_LEG_NONE",
        "H4_REBAL_FIRST": "H1_LEG_NONE", "H5_SPLIT": "H1_LEG_NONE"}
LEG_ARMS = ["H2_LEG_REBAL", "H3_LEG_STEPUP", "H4_REBAL_FIRST", "H5_SPLIT"]

ARM_NOTE = {
    "H0_MKT_STEPUP": "레버리지 없이 시장만 보유 + 매년 12월 공제 한도만큼 팔았다 바로 되사기(원가 올리기)",
    "H1_LEG_NONE": "시장 80 + 2배 다리 20, 적립금으로만 비중 회복, 공제는 쓰지 않는다(쌍둥이 기준)",
    "H2_LEG_REBAL": "H1 + 12월에 공제 한도만큼 다리를 팔아 시장을 산다(= 지금 L20A, 추가 세금 0)",
    "H3_LEG_STEPUP": "H1 + 12월 공제를 전부 시장 보유분 원가 올리기에 쓴다(다리는 적립금으로만 회복)",
    "H4_REBAL_FIRST": "H1 + 12월에 되돌림을 먼저 하고, 남은 공제로 원가 올리기",
    "H5_SPLIT": "H1 + 12월 공제의 절반(125만 원)까지만 되돌림에 쓰고 남은 공제는 원가 올리기",
}
# leg=2배 다리를 쓰는가 · rebal_share=그해 남은 공제 중 되돌림에 쓸 비율 · stepup=남은 공제로 원가를 올리는가
# 한 해 안의 순서는 늘 '되돌림 → 원가 올리기'다(사전 등록).
ARM_CFG = {
    "H0_MKT_STEPUP": {"leg": False, "rebal_share": 0.0, "stepup": True},
    "H1_LEG_NONE": {"leg": True, "rebal_share": 0.0, "stepup": False},
    "H2_LEG_REBAL": {"leg": True, "rebal_share": 1.0, "stepup": False},
    "H3_LEG_STEPUP": {"leg": True, "rebal_share": 0.0, "stepup": True},
    "H4_REBAL_FIRST": {"leg": True, "rebal_share": 1.0, "stepup": True},
    "H5_SPLIT": {"leg": True, "rebal_share": 0.5, "stepup": True},
}


# =================================================================================================
# 가상 역사 / 실제 역사 월 수익
# =================================================================================================

def leg_daily(mkt: np.ndarray, rf: np.ndarray) -> np.ndarray:
    """일일 리셋 2배 상품의 일 수익(필터 없음) — lev-base-v1·frontier-lev-rebal-v1 과 같은 식."""
    return MULT * mkt - (MULT - 1.0) * (rf + FIN_SPREAD / 252) - LEG_FEE / 252


def era_arrays(data: dict, lo: str, hi: str) -> tuple[np.ndarray, np.ndarray]:
    mkt, rf = data["mkt"], data["rf"].reindex(data["mkt"].index).fillna(0.0)
    m = (mkt.index >= pd.Timestamp(lo)) & (mkt.index <= pd.Timestamp(hi)) & mkt.notna().to_numpy()
    return mkt[m].to_numpy(dtype=float), rf[m].to_numpy(dtype=float)


def bootstrap_monthly(mkt: np.ndarray, rf: np.ndarray, months: int, n_paths: int, seed: int,
                      block: int, chunk: int = 250) -> tuple[np.ndarray, np.ndarray]:
    """원형 블록 부트스트랩 가상 역사 → 월 성장배수 (경로, 달). 하루 단위로 2배 상품을 굴린 뒤 21일씩 곱한다."""
    d_need = months * DAYS_PER_MONTH
    rows = L.block_paths(len(mkt), d_need, block, n_paths, seed).astype(np.int32)
    fm = np.empty((n_paths, months)); fl = np.empty((n_paths, months))
    for i in range(0, n_paths, chunk):
        r = rows[i:i + chunk]
        rm, rrf = mkt[r], rf[r]
        rl = leg_daily(rm, rrf)
        fm[i:i + chunk] = (1.0 + rm).reshape(-1, months, DAYS_PER_MONTH).prod(axis=2)
        fl[i:i + chunk] = (1.0 + rl).reshape(-1, months, DAYS_PER_MONTH).prod(axis=2)
    return fm, fl


def real_monthly(data: dict) -> tuple[np.ndarray, np.ndarray, pd.PeriodIndex]:
    """실제 역사(달력 월) 성장배수 — 보고용 비교."""
    mkt = data["mkt"].dropna()
    rf = data["rf"].reindex(mkt.index).fillna(0.0)
    legs = pd.Series(leg_daily(mkt.to_numpy(dtype=float), rf.to_numpy(dtype=float)), index=mkt.index)
    per = mkt.index.to_period("M")
    fm = (1.0 + mkt).groupby(per).prod()
    fl = (1.0 + legs).groupby(per).prod()
    return fm.to_numpy(dtype=float), fl.to_numpy(dtype=float), fm.index


# =================================================================================================
# 계좌 (이동평균 취득원가·연 공제·판 날 즉시 세금 차감)
# =================================================================================================

def _sell(V, B, gross, year_gain):
    """자산에서 평가액 gross 만큼 판다 → (V, B, 현금, 실현이익, 낸 세금). 취득원가는 이동평균."""
    gross = np.clip(gross, 0.0, V)
    frac = np.where(V > 0, gross / np.where(V > 0, V, 1.0), 0.0)
    basis_out = frac * B
    gain = gross - basis_out
    before = CGT * np.maximum(0.0, year_gain - ALLOWANCE)
    after = CGT * np.maximum(0.0, year_gain + gain - ALLOWANCE)
    return V - gross, B - basis_out, gross * (1.0 - SELL_COST) - (after - before), gain, after - before


def _buy(V, B, cash):
    return V + cash * (1.0 - BUY_COST), B + cash


def _gross_for_room(V, B, room, min_rate=0.0):
    """그해 남은 공제(room) 안에서 실현이익이 딱 차도록 팔 수 있는 평가액. 이익률이 min_rate 미만이면 0."""
    rate = np.where(V > 0, 1.0 - B / np.where(V > 0, V, 1.0), 0.0)
    ok = rate > max(min_rate, 1e-9)
    return np.where(ok, room / np.where(ok, rate, 1.0), 0.0)


def simulate(fm: np.ndarray, fl: np.ndarray, arm: str, cal_month: np.ndarray,
             lump: float, monthly: float, want_twr: bool = False) -> dict[str, Any]:
    """팔지 않는(또는 정책대로만 파는) 적립 계좌. fm/fl: (경로, 달) 성장배수. arm='MKT' 는 시장 그냥 보유."""
    P, M = fm.shape
    cfg = ARM_CFG.get(arm, {"leg": False, "rebal_share": 0.0, "stepup": False})
    Vm = np.zeros(P); Bm = np.zeros(P); Vl = np.zeros(P); Bl = np.zeros(P)
    year_gain = np.zeros(P); tax_paid = np.zeros(P)
    harvested = np.zeros(P); n_rebal = np.zeros(P); n_step = np.zeros(P)
    vals = np.zeros((P, M + 1)); expo = np.zeros((P, M))
    twr = np.zeros((P, M)) if want_twr else None

    for t in range(M):
        if cal_month[t] == 0:
            year_gain = np.zeros(P)
        cash = np.full(P, monthly + (lump if t == 0 else 0.0))
        tot = Vm + Vl
        if not cfg["leg"]:
            alloc_l = np.zeros(P)
        elif t == 0:
            alloc_l = TARGET_W * cash                                       # 첫날 목돈도 목표 비중
        else:
            alloc_l = np.clip(TARGET_W * (tot + cash) - Vl, 0.0, cash)      # 적립금은 모자란 쪽부터
        Vl, Bl = _buy(Vl, Bl, alloc_l)
        Vm, Bm = _buy(Vm, Bm, cash - alloc_l)

        if cal_month[t] == HARVEST_MONTH and t > 0:
            room0 = np.maximum(0.0, ALLOWANCE - year_gain)
            # ① 되돌림: 목표 초과분을 공제 한도(또는 그 일부) 안에서만 팔아 시장을 산다 → 추가 세금 0
            if cfg["leg"] and cfg["rebal_share"] > 0:
                over = Vl - TARGET_W * (Vm + Vl)
                room = np.minimum(cfg["rebal_share"] * room0, np.maximum(0.0, ALLOWANCE - year_gain))
                g = np.minimum(np.maximum(over, 0.0), _gross_for_room(Vl, Bl, room))
                Vl, Bl, cashp, gain, tax = _sell(Vl, Bl, g, year_gain)
                year_gain = year_gain + gain; tax_paid = tax_paid + tax
                harvested = harvested + gain; n_rebal += (g > 0)
                Vm, Bm = _buy(Vm, Bm, cashp)
            # ② 원가 올리기: 시장 보유분을 남은 공제만큼 팔았다 바로 되산다(배분·노출 변화 없음)
            if cfg["stepup"]:
                room = np.maximum(0.0, ALLOWANCE - year_gain)
                g = _gross_for_room(Vm, Bm, room, MIN_GAIN_RATE)
                Vm, Bm, cashp, gain, tax = _sell(Vm, Bm, g, year_gain)
                year_gain = year_gain + gain; tax_paid = tax_paid + tax
                harvested = harvested + gain; n_step += (gain > 0)
                Vm, Bm = _buy(Vm, Bm, cashp)

        tot = Vm + Vl
        expo[:, t] = np.where(tot > 0, (Vm + MULT * Vl) / np.where(tot > 0, tot, 1.0), 1.0)
        Vm = Vm * fm[:, t]; Vl = Vl * fl[:, t]
        vals[:, t + 1] = Vm + Vl
        if want_twr:
            twr[:, t] = np.where(tot > 0, vals[:, t + 1] / np.where(tot > 0, tot, 1.0) - 1.0, 0.0)

    gross = Vm + Vl
    w_end = np.where(gross > 0, Vl / np.where(gross > 0, gross, 1.0), 0.0)
    unreal = (Vm - Bm) + (Vl - Bl)
    # 청산은 '다음 해 1월'(새 과세연도)에 한다고 본다 — 모든 팔에 같게 적용하며, 마지막 12월 공제 사용이
    # 청산 공제를 잡아먹는 측정 인공물을 없앤다(사전 등록).
    tax_fin = CGT * np.maximum(0.0, unreal - ALLOWANCE)
    terminal = gross * (1.0 - SELL_COST) - tax_fin
    vals[:, 0] = lump + monthly
    peak = np.maximum.accumulate(vals, axis=1)
    mdd = np.min(vals / np.where(peak > 0, peak, 1.0) - 1.0, axis=1)
    out = {"terminal": terminal, "irr": irr_vec(terminal, M, lump, monthly), "mdd": mdd, "w_end": w_end,
           "tax": tax_paid + tax_fin, "tax_fin": tax_fin, "harvested": harvested,
           "n_rebal": n_rebal, "n_step": n_step, "exposure": expo.mean(axis=1)}
    if want_twr:
        out["twr"] = twr
    return out


def irr_vec(terminal: np.ndarray, months: int, lump: float, monthly: float) -> np.ndarray:
    """월 적립 흐름의 연 IRR(이분법, 경로별). 흐름: 0달 목돈+적립, 1~M-1달 적립, M달 청산액."""
    n = months - 1
    lo = np.full(terminal.shape, -0.9); hi = np.full(terminal.shape, 1.0)

    def npv(i):
        i = np.where(np.abs(i) < 1e-12, 1e-12, i)
        ann = (1.0 - (1.0 + i) ** (-n)) / i
        return -(lump + monthly) - monthly * ann + terminal * (1.0 + i) ** (-months)

    for _ in range(90):
        mid = 0.5 * (lo + hi)
        pos = npv(mid) > 0          # npv 는 i 에 대해 감소 → 양수면 참 IRR 이 더 높다
        lo = np.where(pos, mid, lo); hi = np.where(pos, hi, mid)
    r = 0.5 * (lo + hi)
    out = (1.0 + r) ** 12 - 1.0
    return np.where(np.isfinite(out) & (terminal > 0), out, np.nan)


# =================================================================================================
# 판정
# =================================================================================================

def compare(arm: dict, base: dict) -> list[dict]:
    return [{"diff_irr": float(a - b), "win": bool(x > y)}
            for a, b, x, y in zip(arm["irr"], base["irr"], arm["terminal"], base["terminal"])]


def gate(r: dict, base: dict) -> dict[str, Any]:
    """사전 등록 관문 5개(일관성 위주) — 쌍둥이 base 대비."""
    k = L.kpi_pairs_verdict(compare(r, base), WIN_MIN, MED_MIN, P10_MIN)
    k["checks"]["mdd_within"] = bool(float(np.median(r["mdd"])) >= float(np.median(base["mdd"])) - MDD_GAP_MAX)
    k["checks"]["leg_drift"] = bool(float(np.median(r["w_end"])) <= LEG_W_MAX)
    k["pass"] = bool(all(k["checks"].values()))
    return k


def era_block(res: dict[str, dict]) -> dict[str, Any]:
    mkt = res["MKT"]
    out: dict[str, Any] = {}
    for arm in ARMS:
        r = res[arm]
        twin = res[TWIN.get(arm, "MKT")]
        k = gate(r, twin)
        k_mkt = L.kpi_pairs_verdict(compare(r, mkt), 0.0, -1e9, -1e9)
        # 보조(사전 등록): '지금 정책(L20A = H2)에 원가 올리기를 더하면 나아지나'
        if arm in ("H3_LEG_STEPUP", "H4_REBAL_FIRST", "H5_SPLIT"):
            out.setdefault(arm, {})["vs_L20A"] = gate(r, res["H2_LEG_REBAL"])
        out[arm] = {**out.get(arm, {}), "vs_twin": k, "vs_market": k_mkt, "twin": TWIN.get(arm, "MKT"),
                    "median_irr": float(np.nanmedian(r["irr"])), "median_mdd": float(np.median(r["mdd"])),
                    "median_w_end": float(np.median(r["w_end"])), "median_exposure": float(np.median(r["exposure"])),
                    "median_tax_krw": float(np.median(r["tax"])), "median_tax_fin_krw": float(np.median(r["tax_fin"])),
                    "median_harvested_krw": float(np.median(r["harvested"])),
                    "median_n_rebal": float(np.median(r["n_rebal"])), "median_n_step": float(np.median(r["n_step"])),
                    "median_terminal_krw": float(np.median(r["terminal"])),
                    "mdd_vs_market_pp": float(np.median(r["mdd"])) - float(np.median(mkt["mdd"]))}
    out["MKT"] = {"median_irr": float(np.nanmedian(mkt["irr"])), "median_mdd": float(np.median(mkt["mdd"])),
                  "p10_mdd": float(np.percentile(mkt["mdd"], 10)),
                  "median_terminal_krw": float(np.median(mkt["terminal"])), "median_tax_krw": float(np.median(mkt["tax"]))}
    return out


# =================================================================================================
# 본문
# =================================================================================================

def body(run):
    smoke = run.smoke
    months = 60 if smoke else HORIZON_MONTHS
    n_paths = 60 if smoke else N_PATHS
    block = 21 if smoke else BLOCK_DAYS

    data = run.stage("data", lambda: (L.load_long_synthetic() if smoke else L.load_long_real()))
    source = data["source"]
    cal = np.arange(months) % 12          # 가상 역사: 첫 달을 1월로 본다

    def do_era(name: str, lo: str, hi: str, seed_add: int):
        mkt, rf = era_arrays(data, lo, hi)
        if len(mkt) < block * 4:
            return {"n_days": int(len(mkt)), "skipped": True}
        fm, fl = bootstrap_monthly(mkt, rf, months, n_paths, SEED + seed_add, block)
        blk: dict[str, Any] = {"n_days": int(len(mkt)), "n_paths": int(n_paths), "months": int(months)}
        for sc, (lump, monthly) in SCENARIOS.items():
            res = {}
            for arm in ["MKT", *ARMS]:
                run.check_time()
                res[arm] = simulate(fm, fl, arm, cal, lump, monthly)
            blk[sc] = era_block(res)
        return blk

    eras: dict[str, Any] = {}
    for i, (name, (lo, hi)) in enumerate([*ERAS.items(), *REPORT_ERAS.items()]):
        eras[name] = run.stage(f"era_{name}", lambda name=name, lo=lo, hi=hi, i=i: do_era(name, lo, hi, 101 * (i + 1)))

    # 실제 역사(겹치지 않는 구간 + 전체 한 경로, 판정 시나리오만) — 보고만
    def do_real():
        fm, fl, per = real_monthly(data)
        lump, monthly = SCENARIOS[JUDGE_SCENARIO]
        cm = np.array([p.month - 1 for p in per])
        rows = []
        for s in range(0, len(fm) - months + 1, months):
            sl = slice(s, s + months)
            r = {a: simulate(fm[None, sl], fl[None, sl], a, cm[sl], lump, monthly) for a in ["MKT", *ARMS]}
            rows.append({"start": str(per[s]), "end": str(per[s + months - 1]),
                         **{a: {"irr": float(r[a]["irr"][0]), "mdd": float(r[a]["mdd"][0]),
                                "w_end": float(r[a]["w_end"][0]), "tax": float(r[a]["tax"][0]),
                                "harvested": float(r[a]["harvested"][0])} for a in ["MKT", *ARMS]}})
            if len(rows) >= (2 if smoke else 99):
                break
        n = len(fm)
        fr = {a: simulate(fm[None, :n], fl[None, :n], a, cm[:n], lump, monthly, want_twr=True) for a in ["MKT", *ARMS]}
        full = {"start": str(per[0]), "end": str(per[-1]), "months": int(n),
                **{a: {"irr": float(fr[a]["irr"][0]), "mdd": float(fr[a]["mdd"][0]), "w_end": float(fr[a]["w_end"][0]),
                       "tax": float(fr[a]["tax"][0]), "harvested": float(fr[a]["harvested"][0])} for a in ["MKT", *ARMS]}}
        act = {a: (fr[a]["twr"][0] - fr[TWIN.get(a, "MKT")]["twr"][0]).tolist() for a in ARMS}
        return {"windows": rows, "full": full, "active": act}

    real = run.stage("real", do_real)

    # 판정 — 두 era(selection·confirmation) 모두, 판정 시나리오(S1)에서 통과해야 한다
    power = rp.power_report(months / 12.0, len(JUDGED))
    verdicts: dict[str, str] = {}
    for arm in JUDGED:
        act = np.array(real["active"].get(arm, []), dtype=float)
        if rp.noop_guard(act.tolist()) is not None:
            verdicts[arm] = "NOT_EVALUABLE"
            continue
        ok = [eras[e].get(JUDGE_SCENARIO, {}).get(arm, {}).get("vs_twin", {}).get("pass") for e in ERAS]
        if all(bool(x) for x in ok):
            verdicts[arm] = "ALLOWANCE_HELPS"
        else:
            ir = float(np.nanmean(act) / np.nanstd(act) * math.sqrt(12)) if len(act) > 2 and np.nanstd(act) > 0 else None
            verdicts[arm] = rp.classify_fail(ir, power)

    # 프런티어 후보 고르기(사전 등록 규칙): 레버리지 팔 가운데 ① 말기 다리 비중 ≤ 30%
    # ② 시장 대비 낙폭 10%p 이내 ③ 두 시대 모두 시장보다 세후 IRR 중앙값이 높음 — 를 모두 만족하는 팔 중
    # '두 시대 최소 세후 IRR 중앙값'이 가장 큰 것.
    def eligible(a: str) -> bool:
        for e in ERAS:
            x = eras[e].get(JUDGE_SCENARIO, {}).get(a)
            m = eras[e].get(JUDGE_SCENARIO, {}).get("MKT")
            if not x or not m:
                return False
            if x["median_w_end"] > LEG_W_MAX or x["mdd_vs_market_pp"] < -MKT_MDD_GAP_MAX:
                return False
            if x["median_irr"] <= m["median_irr"]:
                return False
        return True

    ok_arms = [a for a in LEG_ARMS if eligible(a)]
    if ok_arms:
        verdicts["frontier_pick"] = max(ok_arms, key=lambda a: min(
            eras[e][JUDGE_SCENARIO][a]["median_irr"] for e in ERAS))
    else:
        verdicts["frontier_pick"] = "NO_ELIGIBLE_ARM"

    def diff(e: str, a: str, key: str = "vs_twin"):
        x = eras[e].get(JUDGE_SCENARIO, {}).get(a, {})
        v = (x.get(key) or {}).get("median_diff_irr")
        return v if isinstance(v, (int, float)) and math.isfinite(float(v)) else None

    def pp(v) -> str:
        return "—" if v is None else f"{v * 100:+.2f}%p"

    verdicts["stepup_on_market"] = (" / ".join(pp(diff(e, "H0_MKT_STEPUP")) for e in ERAS) +
                                    " (SPY 그냥 보유 대비 세후 IRR 중앙값, 선택/확인)")
    # 보조(사전 등록): 지금 정책 L20A(H2) 위에 원가 올리기를 더하면 같은 관문을 통과하나
    for a in ("H4_REBAL_FIRST", "H5_SPLIT"):
        ok = all(bool((eras[e].get(JUDGE_SCENARIO, {}).get(a, {}).get("vs_L20A") or {}).get("pass")) for e in ERAS)
        verdicts[f"{a}_on_top_of_L20A"] = ("STEPUP_ADDS" if ok else "NOT_ADDING") + \
            " (" + " / ".join(pp(diff(e, a, "vs_L20A")) for e in ERAS) + ")"
    sel_step, sel_reb = diff("selection", "H3_LEG_STEPUP"), diff("selection", "H2_LEG_REBAL")
    if sel_step is None or sel_reb is None:
        verdicts["allowance_use"] = "측정 불가"
    else:
        verdicts["allowance_use"] = ("원가 올리기" if sel_step > sel_reb else "되돌림") + \
            f" 가 선택 시대 세후 IRR 우위(원가 {pp(sel_step)} 대 되돌림 {pp(sel_reb)}, 둘 다 H1 대비)"

    result = {"id": "frontier-tax-allowance-v1", "rules_version": RULES_VERSION, "smoke": smoke, "source": source,
              "scenario": {"scenarios": {k: list(v) for k, v in SCENARIOS.items()}, "judge_scenario": JUDGE_SCENARIO,
                           "months": months, "target_leg_weight": TARGET_W, "n_paths": n_paths, "block_days": block,
                           "harvest_month": HARVEST_MONTH + 1, "min_gain_rate": MIN_GAIN_RATE},
              "thresholds": {"win_min": WIN_MIN, "median_irr_min": MED_MIN, "p10_irr_min": P10_MIN,
                             "mdd_gap_max": MDD_GAP_MAX, "leg_w_max": LEG_W_MAX, "mkt_mdd_gap_max": MKT_MDD_GAP_MAX},
              "power": power, "eras": L.rnd(eras), "real_history": L.rnd(real["windows"]),
              "real_full": L.rnd(real["full"]), "verdicts": verdicts}
    return result, report(result)


def man(x) -> str:
    """원 → '…만 원'(None·비유한 안전)."""
    if x is None or not (isinstance(x, (int, float)) and math.isfinite(float(x))):
        return "—"
    return f"{float(x) / 1e4:,.0f}만 원"


def num(x, nd: int = 2) -> str:
    if x is None or not (isinstance(x, (int, float)) and math.isfinite(float(x))):
        return "—"
    return f"{float(x):.{nd}f}"


def report(r: dict) -> str:
    e = r["eras"]
    sc = r["scenario"]
    js = sc["judge_scenario"]
    lines = [f"# 연 250만 원 공제를 어디에 쓸까 — 끝없는 적립 (frontier-tax-allowance-v1/{RULES_VERSION.split('/')[-1]})", "",
             "팔지 않는 적립 계좌는 해마다 양도세 기본공제(250만 원)를 그냥 버린다. 쓰는 길은 두 가지다:",
             "**되돌림**(레버리지 다리를 공제만큼만 팔아 시장을 산다 — 위험 통제)과 **원가 올리기**(시장 보유분을 공제만큼 팔았다 바로 되산다 —",
             "배분·시장 노출은 그대로이고 청산 세금만 줄어든다). 공제는 한 해에 하나뿐이라 둘은 경쟁한다. 순서를 정하면 둘 다 얻는지 본다.", "",
             "**판정:** " + " · ".join(f"{k} **{r['verdicts'][k]}**" for k in JUDGED), "",
             f"- SPY 그냥 보유에 원가 올리기만 더하면: **{r['verdicts'].get('stepup_on_market')}**",
             f"- 프런티어 후보(레버리지 팔 중): **{r['verdicts'].get('frontier_pick')}** · {r['verdicts'].get('allowance_use')}",
             "- 지금 정책 L20A 위에 원가 올리기를 더하면(보조): " +
             " · ".join(f"{a} {r['verdicts'].get(a + '_on_top_of_L20A')}" for a in ("H4_REBAL_FIRST", "H5_SPLIT")), "",
             "통과는 '전진 원장 후보'일 뿐 엔진 채택이 아니다. 엔진은 바뀌지 않았다.", "",
             "## 규칙 (결과를 보기 전에 고정)", "",
             f"- 계좌(판정): {js} = 처음 {SCENARIOS[js][0]:,.0f} 원 + 매달 {SCENARIOS[js][1]:,.0f} 원. 매수·매도마다 0.15%(수수료 0.1% + 환전 0.05%).",
             "  취득원가는 이동평균, 양도세 22% × max(0, 그해 실현이익 − 250만 원)을 판 즉시 현금에서 뺀다.",
             "  청산은 **다음 해 1월**(새 과세연도)에 한다고 본다 — 마지막 12월의 공제 사용이 청산 공제를 잡아먹는 측정 인공물을 없애기 위해 모든 팔에 같게 적용.",
             f"- 다리: 필터 없는 고정 2배(일일 리셋, 차입 가산 연 1% + 보수 연 0.9%), 목표 비중 {TARGET_W:.0%}. 가격 신호는 쓰지 않는다.",
             f"- 원가 올리기는 매년 {sc['harvest_month']}월에만, 평가이익률이 {MIN_GAIN_RATE:.0%} 이상일 때만 한다(왕복 비용 0.3% ÷ 세율 22% ≈ 1.36% 가 손익분기 → 안전 여유).",
             "- 팔(6개): " + " · ".join(f"{a}={ARM_NOTE[a]}" for a in ARMS),
             "- 쌍둥이 비교: " + " · ".join(f"{a}↔{TWIN[a]}" for a in JUDGED) + " (같은 위험·같은 배분끼리 비교해 세금 효과만 떼어 본다).",
             f"- 통과(ALLOWANCE_HELPS) ⇔ **두 시대 모두** ① 쌍둥이보다 많이 남은 경로 ≥ {WIN_MIN:.0%} ② 세후 IRR 차이 중앙값 ≥ {MED_MIN * 100:+.2f}%p "
             f"③ 10분위 ≥ {P10_MIN * 100:+.2f}%p ④ 낙폭 중앙값이 쌍둥이보다 {MDD_GAP_MAX * 100:.1f}%p 넘게 나쁘지 않음 ⑤ 말기 다리 비중 중앙값 ≤ {LEG_W_MAX:.0%}.",
             "  (위험 없는 이득이므로 크기보다 **일관성**을 본다 — 작아도 거의 항상 이겨야 통과다.)",
             f"- 가상 역사: 원형 블록 부트스트랩(블록 {sc['block_days']}거래일), 시대마다 경로 {sc['n_paths']}개, {sc['months']}달 — selection(1927~1966 일자) · confirmation(1967~2007 일자). 2008+ 는 보고만.",
             "- 계좌 크기 3종(S1 판정 / S2 목돈 0+월 10만 / S3 1억+월 100만)은 **보고만** — 공제는 정액이라 계좌가 커지면 효과가 묽어진다.",
             f"- 판정 팔 {len(JUDGED)}개뿐이고 문턱·시나리오·공제 사용 순서는 결과를 보기 전에 고정했다. 가격 격자를 키우는 연구가 아니다(가격 규칙이 없다).",
             "  겹침 공시: 공제 한도 되돌림(H2)은 frontier-lev-rebal-v1 의 A4_ALLOW 와 같은 규칙이고(여기서는 쌍둥이 기준으로만 쓴다),",
             "  '연말 공제 채우기'는 tax-rnd-v1 V1 이 **자주 매매하는 코어·목돈 3,000만 원·ETF 한 역사**에서 한 번 봤다(+0.05%p, FAIL).",
             "  여기서는 **팔지 않는 적립 계좌·30년·가상 역사 두 시대**이고, 공제가 되돌림과 경쟁하는지가 새 질문이다. 1927~2024 가격은 이미 여러 연구가 본 자료다.", "",
             "- " + rp.power_line(r["power"]),
             "  (주의: IR 기반 검정력은 **세전 수익 경로**에 대한 것이다. 이 연구의 효과는 세전 수익이 아니라 청산 세금에 있으므로, 낸 세금·원가 올린 금액 열을 함께 읽어야 한다.)", "",
             f"자료: {r['source']}", ""]
    for name in [*ERAS, *REPORT_ERAS]:
        b = e.get(name, {})
        if not b or b.get("skipped"):
            lines += [f"## {name} — 자료 부족으로 건너뜀", ""]
            continue
        tag = " (보고만)" if name in REPORT_ERAS else ""
        for scn in SCENARIOS:
            blk = b.get(scn, {})
            if not blk:
                continue
            mark = "판정" if scn == js and name in ERAS else "보고만"
            lump, monthly = SCENARIOS[scn]
            lines += [f"## {name}{tag} · {scn}(목돈 {lump / 1e4:,.0f}만 + 월 {monthly / 1e4:,.0f}만, {mark}) — 가상 역사 {b.get('n_paths')}개, {b.get('months')}달", "",
                      "| 팔 | 쌍둥이 | 이긴 비율 | IRR 차이 중앙/10분위 | 세후 IRR 중앙 | 계좌 낙폭 중앙 | 말기 다리 비중 | 평균 노출 | 원가 올린 이익 | 청산 세금 중앙 | 관문 |",
                      "|---|---|---|---|---|---|---|---|---|---|---|"]
            m = blk.get("MKT", {})
            lines.append(f"| 시장 그냥 보유 | — | — | — | {L.pct(m.get('median_irr'))} | {L.pct(m.get('median_mdd'), True)} | — | 1.00 | — | {man(m.get('median_tax_krw'))} | 기준 |")
            for a in ARMS:
                x = blk.get(a, {})
                vt = x.get("vs_twin") or {}
                ck = ",".join(k for k, v in (vt.get("checks") or {}).items() if not v) or "모두 충족"
                lines.append(f"| {a} | {x.get('twin')} | {L.pct(vt.get('share_win'))} | {L.pct(vt.get('median_diff_irr'), True, 2)} / {L.pct(vt.get('p10_diff_irr'), True, 2)} | "
                             f"{L.pct(x.get('median_irr'))} | {L.pct(x.get('median_mdd'), True)} | {L.pct(x.get('median_w_end'))} | "
                             f"{num(x.get('median_exposure'))} | {man(x.get('median_harvested_krw'))} | "
                             f"{man(x.get('median_tax_fin_krw'))} | {ck} |")
            lines.append("")
            extra = [(a, blk.get(a, {}).get("vs_L20A") or {}) for a in ("H3_LEG_STEPUP", "H4_REBAL_FIRST", "H5_SPLIT")]
            extra = [(a, v) for a, v in extra if v]
            if extra:
                lines += ["지금 정책 L20A(H2_LEG_REBAL) 위에 더했을 때(보조): " +
                          " · ".join(f"{a} {L.pct(v.get('median_diff_irr'), True, 2)}"
                                     f"(이긴 비율 {L.pct(v.get('share_win'))}, "
                                     f"{'관문 통과' if v.get('pass') else '미달: ' + (','.join(k for k, z in (v.get('checks') or {}).items() if not z) or '—')})"
                                     for a, v in extra), ""]
    lines += ["## 실제 역사(겹치지 않는 30년 구간 · 보고만)", "",
              "| 구간 | " + " | ".join(ARMS) + " | 시장 |", "|---|" + "---|" * (len(ARMS) + 1)]
    for w in r["real_history"]:
        lines.append(f"| {w['start']}~{w['end']} | " + " | ".join(L.pct(w[a]["irr"]) for a in ARMS) + f" | {L.pct(w['MKT']['irr'])} |")
    f = r["real_full"]
    lines += ["", f"전체 한 경로({f['start']}~{f['end']}, {f['months']}달): " +
              " · ".join(f"{a} IRR {L.pct(f[a]['irr'])}/낙폭 {L.pct(f[a]['mdd'], True)}/원가 올린 이익 {man(f[a].get('harvested'))}"
                         for a in ["MKT", *ARMS]), "",
              "## 주의", "",
              "- 핵심 가정: 한국 해외주식 양도소득세에는 **wash-sale 규정이 없다** — 팔았다 같은 날 되사도 취득원가가 새로 잡힌다. 세법이 바뀌면 이 연구의 결론은 무효다.",
              "- 팔았다 되사기를 **같은 날 같은 가격**으로 본다(실제로는 몇 분~몇 시간 사이 가격이 움직인다). 비용은 왕복 0.3% 만 뗐다.",
              "- 취득원가는 **이동평균법**이다(증권사에 따라 다를 수 있다). 환율은 1,300원 고정 근사라 환율로 생기는 양도차익은 빠졌다.",
              "- 계좌 낙폭은 **월말 가치** 기준이라 달 안의 더 깊은 낙폭은 빠진다(모든 팔에 같게 적용).",
              "- 가상 역사는 블록을 섞은 '겹치지 않는' 표본이지만 원재료는 같은 미국 역사다. 완전히 새로운 정보는 아니다.",
              "- 다리는 **합성 2배**다. 실제 상품(SSO)·정밀 세금은 engine-candidate-v1 이 2006~2024 한 역사에서만 확인했다.",
              "- 금융소득종합과세·건강보험료·배당 원천징수는 넣지 않았다. 세금은 '판 즉시 차감'이라 실제(다음 해 5월 납부)보다 약간 불리하다.",
              "- 통과해도 **전진 원장에 올릴 후보**일 뿐이다. 투자 조언이 아니다."]
    return "\n".join(lines)


if __name__ == "__main__":
    runner = L.Runner(RULES_VERSION)
    raise SystemExit(runner.run(body))
