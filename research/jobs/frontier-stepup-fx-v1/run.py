"""frontier-stepup-fx-v1 — 원가 올리기에 환율을 넣으면 그 이득이 남나 (사전 등록 2026-11-25).

frontier-tax-allowance-v2 에서 루프의 첫 '위험 없는' 통과가 나왔다: 팔지 않는 적립 계좌가 해마다 버리는
양도세 기본공제(250만 원)를 **시장 보유분을 팔았다 바로 되사 취득원가를 올리는 데** 쓰면, 시장 노출·낙폭을
1도 바꾸지 않고 세후 IRR 중앙값이 +0.12%p(선택) / +0.09%p(확인) 늘었다(이긴 경로 93.5 / 96.0%).

그 연구의 가장 큰 미검증 가정은 **환율 1,300원 고정**이다. 한국 해외주식 양도소득세는 **원화 기준**이다 —
  양도차익 = 양도가액 × 매도일 환율 − 취득가액 × 매수일 환율
이라서 환율은 과세 대상의 **크기와 부호를 함께** 바꾼다. 원화가 약해지면 달러 자산의 원화 차익이 부풀어
공제가 빨리 차고(원가를 더 많이 올릴 수 있다) 청산 세금도 커진다. 원화가 강해지면 달러로는 이익인데
원화로는 손실이라 그해 공제를 아예 쓸 수 없다. 그래서 효과가 커질지 작아질지 **부호조차 미지**다.

또 liquidation-accounting-impact-v1 은 청산 회계 관례 하나만 바꿔도 세후 IRR 차이가 ±0.04%p 움직이고
117창 중 2창은 승패가 뒤집힘을 보였다. +0.1%p 급 주장은 **다른 구현에서도 부호가 유지되는지** 확인해야 증거가 된다.

이 연구가 묻는 것(판정 4개):
  A_STEPUP_KRW   실제 환율 + 원화 이익률로 공제를 채운다 → 쌍둥이(같은 환율, 공제 미사용)보다 나은가  ← 주 판정
  B_STEPUP_FIX   환율 1,300원 고정(= v2 모델)을 같은 가격 경로에서 다시 재는 재현 검사
  C_STEPUP_USD   실제 환율인데 **달러 이익률**로 공제를 채운다(환율을 잊은 구현) → 초과 실현(세금)·공제 낭비로 이득을 잃나
  D_L20A_STEPUP  L20A(시장 80 + 2배 다리 20, 12월 공제 한도 되돌림) 위에 남은 공제로 원가 올리기 → 환율 아래에서도 보탬이 없나

가격 규칙이 한 줄도 없다(이동평균·손절률·상위 N·기간 격자를 키우지 않는다). 새 자료는 **원/달러 일별(DEXKOUS 1981-04~)**
이고, 이것을 시장 수익과 **같은 날짜 덩어리로 함께** 블록 부트스트랩에 넣어 쓴 프런티어 연구는 없다
(engine-candidate-v1 이 2006~2024 한 역사에서만 실제 환율을 썼다).

판정 문턱·비교 대상·구간·계좌 모델은 아래 상수와 SPEC.md 에 결과를 보기 전에 고정했고 이후 바꾸지 않는다.
문턱은 부모 연구(frontier-tax-allowance-v2)의 것을 **한 글자도 바꾸지 않고** 그대로 쓴다 — 전이 검사의 핵심이다.
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
RULES_VERSION = "frontier-stepup-fx-v1/2026-11-25"

# 돈 — 판정은 S1 만. 나머지는 보고만(공제는 정액이라 계좌가 커지면 효과가 묽어진다).
SCENARIOS = {"S1": (10_000_000.0, 150_000.0), "S2": (0.0, 100_000.0), "S3": (100_000_000.0, 1_000_000.0)}
JUDGE_SCENARIO = "S1"

BUY_COST = L.FEE + L.FX_SPREAD                    # 0.1% 수수료 + 0.05% 환전
SELL_COST = L.FEE + L.FX_SPREAD
CGT, ALLOWANCE = L.CGT, L.ALLOWANCE               # 22%, 연 250만 원
FX0 = L.FX                                        # 시작 환율 1,300원 (고정 환율 팔은 끝까지 이 값)
HARVEST_MONTH = 11                                # 12월(한국 연말 절세 매도 관행) — 부모 연구와 같다
MIN_GAIN_RATE = 0.02                              # 원가 올리기 최소 이익률(왕복 0.3% ÷ 22% ≈ 1.36% 손익분기 + 여유)

# 다리 (필터 없음 — 가격 타이밍을 쓰지 않는다. l15f-robust-v1·lev-weight-frontier-v1 통과 칸)
TARGET_W = 0.20
MULT, FIN_SPREAD, LEG_FEE = 2.0, 0.010, 0.009

# 구간·가상 역사 — 환율 자료가 있는 기간만(DEXKOUS 1981-04-13~). 두 시대 모두 통과해야 한다.
HORIZON_MONTHS = 360                              # 30년 = '끝없음' 대리
DAYS_PER_MONTH, BLOCK_DAYS = 21, 63
N_PATHS, SEED = 2000, 20261125
ERAS = {"fx_a": ("1981-04-13", "2002-12-31"), "fx_b": ("2003-01-01", "2024-09-30")}
REPORT_ERAS = {"fx_full": ("1981-04-13", "2100-01-01")}   # 두 시대를 합친 눈 — 보고만

# 판정 문턱 — 부모 연구(frontier-tax-allowance-v2)와 같다. '위험 없는 이득'이라 크기보다 일관성을 본다.
WIN_MIN, MED_MIN, P10_MIN = 0.90, 0.0005, 0.0     # 이긴 경로 ≥ 90%, 중앙 ≥ +0.05%p, 10분위 ≥ 0
MDD_GAP_MAX = 0.005                               # 쌍둥이보다 낙폭 중앙값이 0.5%p 넘게 나빠지면 탈락
LEG_W_MAX = 0.30                                  # 말기 다리 비중 중앙값 상한(드리프트 위험 통제)
EVAL_TOL_KRW = 1.0                                # 세후 청산액이 쌍둥이와 1원 넘게 다른 경로가 없으면 판정 불가

ARMS = ["T_HOLD_REAL", "A_STEPUP_KRW", "C_STEPUP_USD", "T_HOLD_FIX", "B_STEPUP_FIX",
        "T_HOLD_L20A", "D_L20A_STEPUP"]
JUDGED = ["A_STEPUP_KRW", "B_STEPUP_FIX", "C_STEPUP_USD", "D_L20A_STEPUP"]
TWIN = {"A_STEPUP_KRW": "T_HOLD_REAL", "C_STEPUP_USD": "T_HOLD_REAL",
        "B_STEPUP_FIX": "T_HOLD_FIX", "D_L20A_STEPUP": "T_HOLD_L20A"}

ARM_NOTE = {
    "T_HOLD_REAL": "실제 환율 · 시장만 보유 · 공제 미사용(쌍둥이 기준)",
    "A_STEPUP_KRW": "실제 환율 · 시장만 보유 · 12월에 **원화 이익률**로 공제를 채워 팔았다 바로 되사기 ← 주 판정",
    "C_STEPUP_USD": "실제 환율 · 시장만 보유 · 12월에 **달러 이익률**로 공제를 채운다(환율을 잊은 구현)",
    "T_HOLD_FIX": "환율 1,300원 고정 · 시장만 보유 · 공제 미사용(쌍둥이 기준)",
    "B_STEPUP_FIX": "환율 1,300원 고정 · 시장만 보유 · 원가 올리기(= frontier-tax-allowance-v2 H0 모델 재현)",
    "T_HOLD_L20A": "실제 환율 · 시장 80 + 2배 다리 20 · 12월 공제 한도 안 되돌림(= 지금 L20A, 쌍둥이 기준)",
    "D_L20A_STEPUP": "실제 환율 · L20A + 되돌림 뒤 **남은 공제**로 원가 올리기",
}
# leg=2배 다리 · rebal=12월 공제 한도 안 되돌림 · stepup=None/'krw'/'usd' · fx='real'/'fix'
# 한 해 안의 순서는 늘 '되돌림 → 원가 올리기'다(부모 연구와 같게 사전 등록).
ARM_CFG = {
    "T_HOLD_REAL": {"leg": False, "rebal": False, "stepup": None, "fx": "real"},
    "A_STEPUP_KRW": {"leg": False, "rebal": False, "stepup": "krw", "fx": "real"},
    "C_STEPUP_USD": {"leg": False, "rebal": False, "stepup": "usd", "fx": "real"},
    "T_HOLD_FIX": {"leg": False, "rebal": False, "stepup": None, "fx": "fix"},
    "B_STEPUP_FIX": {"leg": False, "rebal": False, "stepup": "krw", "fx": "fix"},
    "T_HOLD_L20A": {"leg": True, "rebal": True, "stepup": None, "fx": "real"},
    "D_L20A_STEPUP": {"leg": True, "rebal": True, "stepup": "krw", "fx": "real"},
}


# =================================================================================================
# 자료 — 시장(Ken French 일별 총수익)과 원/달러를 같은 평일 달력에 맞춘다
# =================================================================================================

def load_fx_real() -> pd.Series:
    """원/달러 일별(FRED DEXKOUS → 캐시 → yfinance). core.tax_fx 의 로더를 그대로 쓴다."""
    from core import tax_fx as tx

    s = tx.usdkrw_series().dropna().astype(float)
    s = s[s > 0.0]
    if s.empty:
        raise RuntimeError("원/달러 자료를 받지 못함")
    idx = pd.DatetimeIndex(s.index)
    if getattr(idx, "tz", None) is not None:      # yfinance 대체 경로는 시간대가 붙어 올 수 있다
        idx = idx.tz_convert(None)
    s.index = idx.normalize()
    return s[~s.index.duplicated(keep="last")].sort_index()


def load_fx_synthetic(index: pd.DatetimeIndex, mkt: pd.Series, seed: int = 11) -> pd.Series:
    """스모크용 가짜 환율(네트워크 없음). 원화가 천천히 약해지고, 시장이 빠질 때 더 약해지게(음의 상관) 만든다."""
    rng = np.random.default_rng(seed)
    m = mkt.reindex(index).fillna(0.0).to_numpy(dtype=float)
    r = 0.00006 - 0.15 * m + rng.normal(0.0, 0.003, len(index))
    return pd.Series(FX0 * np.cumprod(1.0 + r), index=index)


def fx_daily_return(mkt_index: pd.DatetimeIndex, fx: pd.Series) -> pd.Series:
    """환율을 시장 달력에 맞춘 뒤(앞으로 채우기) 일 변화율. 시장 달력에만 있는 날은 전날 환율을 쓴다."""
    s = fx.reindex(mkt_index.union(fx.index)).sort_index().ffill().reindex(mkt_index)
    return s.pct_change()


def era_arrays(mkt: pd.Series, rf: pd.Series, fxr: pd.Series, lo: str, hi: str):
    m = ((mkt.index >= pd.Timestamp(lo)) & (mkt.index <= pd.Timestamp(hi))
         & mkt.notna().to_numpy() & fxr.notna().to_numpy())
    return (mkt[m].to_numpy(dtype=float), rf[m].to_numpy(dtype=float), fxr[m].to_numpy(dtype=float),
            mkt.index[m])


def leg_daily(mkt: np.ndarray, rf: np.ndarray) -> np.ndarray:
    """일일 리셋 2배 상품의 일 수익(필터 없음) — lev-base-v1·frontier-lev-rebal-v1 과 같은 식."""
    return MULT * mkt - (MULT - 1.0) * (rf + FIN_SPREAD / 252) - LEG_FEE / 252


def bootstrap_monthly(mkt: np.ndarray, rf: np.ndarray, fxr: np.ndarray, months: int, n_paths: int,
                      seed: int, block: int, chunk: int = 200):
    """원형 블록 부트스트랩 → 월 성장배수 (경로, 달) 세 개: 시장·2배 다리·환율.
    한 경로 안에서 시장·금리·환율이 **같은 날짜 덩어리**를 쓰므로 위기 때의 환율 움직임이 보존된다."""
    d_need = months * DAYS_PER_MONTH
    rows = L.block_paths(len(mkt), d_need, block, n_paths, seed).astype(np.int32)
    fm = np.empty((n_paths, months)); fl = np.empty((n_paths, months)); ff = np.empty((n_paths, months))
    for i in range(0, n_paths, chunk):
        r = rows[i:i + chunk]
        rm, rrf, rf_x = mkt[r], rf[r], fxr[r]
        rl = leg_daily(rm, rrf)
        fm[i:i + chunk] = (1.0 + rm).reshape(-1, months, DAYS_PER_MONTH).prod(axis=2)
        fl[i:i + chunk] = (1.0 + rl).reshape(-1, months, DAYS_PER_MONTH).prod(axis=2)
        ff[i:i + chunk] = (1.0 + rf_x).reshape(-1, months, DAYS_PER_MONTH).prod(axis=2)
    return fm, fl, ff


def real_monthly(mkt: np.ndarray, rf: np.ndarray, fxr: np.ndarray, idx: pd.DatetimeIndex):
    """실제 역사(달력 월) 성장배수 — 보고용. 환율은 수준이 아니라 변화율만 쓴다(모든 팔이 1,300원에서 출발)."""
    m = np.asarray(mkt, dtype=float)
    r = np.asarray(rf, dtype=float)
    per = idx.to_period("M")
    fm = (1.0 + pd.Series(m, index=idx)).groupby(per).prod()
    fl = (1.0 + pd.Series(leg_daily(m, r), index=idx)).groupby(per).prod()
    ff = (1.0 + pd.Series(np.asarray(fxr, dtype=float), index=idx)).groupby(per).prod()
    return fm.to_numpy(dtype=float), fl.to_numpy(dtype=float), ff.to_numpy(dtype=float), fm.index


# =================================================================================================
# 계좌 — 달러 자산을 들고, 세금은 원화 차익에 매긴다
# =================================================================================================

def _safe(v: np.ndarray) -> np.ndarray:
    return np.where(v > 0, v, 1.0)


def _buy(V_usd, B_krw, B_usd, cash_krw, fx):
    """원화 cash_krw 를 달러로 바꿔 산다. 취득가액(원화)은 쓴 원화 전액."""
    usd = cash_krw / fx
    return V_usd + usd * (1.0 - BUY_COST), B_krw + cash_krw, B_usd + usd


def _sell(V_usd, B_krw, B_usd, gross_usd, fx, year_gain):
    """달러 평가액 gross_usd 만큼 판다. 양도차익은 **원화**로 잰다(이동평균 취득가액).
    반환: (V_usd, B_krw, B_usd, 받은 원화, 실현 원화차익, 더 낸 세금)."""
    gross_usd = np.clip(gross_usd, 0.0, V_usd)
    frac = np.where(V_usd > 0, gross_usd / _safe(V_usd), 0.0)
    bk_out, bu_out = frac * B_krw, frac * B_usd
    gross_krw = gross_usd * fx
    gain = gross_krw - bk_out
    before = CGT * np.maximum(0.0, year_gain - ALLOWANCE)
    after = CGT * np.maximum(0.0, year_gain + gain - ALLOWANCE)
    cash = gross_krw * (1.0 - SELL_COST) - (after - before)
    return V_usd - gross_usd, B_krw - bk_out, B_usd - bu_out, cash, gain, after - before


def _gross_usd_room_krw(V_usd, B_krw, room_krw, fx, min_rate):
    """그해 남은 공제(원화)가 딱 차도록 팔 달러 평가액 — **원화 이익률**로 계산(법에 맞는 계산)."""
    krw_val = V_usd * fx
    rate = np.where(krw_val > 0, 1.0 - B_krw / _safe(krw_val), 0.0)
    ok = rate > max(min_rate, 1e-9)
    gross_krw = np.where(ok, room_krw / np.where(ok, rate, 1.0), 0.0)
    return np.minimum(gross_krw / fx, V_usd)


def _gross_usd_room_usd(V_usd, B_usd, room_krw, fx, min_rate):
    """환율을 잊은 구현: **달러 이익률**로 '공제를 오늘 환율로 환산한 달러 이익'을 채운다.
    실제로 실현되는 원화차익은 매수일 환율 때문에 이보다 많거나 적다(초과 → 세금, 미달 → 공제 낭비)."""
    rate = np.where(V_usd > 0, 1.0 - B_usd / _safe(V_usd), 0.0)
    ok = rate > max(min_rate, 1e-9)
    target_usd_gain = room_krw / fx
    gross = np.where(ok, target_usd_gain / np.where(ok, rate, 1.0), 0.0)
    return np.minimum(gross, V_usd)


def simulate(fm: np.ndarray, fl: np.ndarray, fxl: np.ndarray, arm: str, cal_month: np.ndarray,
             lump: float, monthly: float, want_twr: bool = False) -> dict[str, Any]:
    """팔지 않는(정책대로만 파는) 원화 적립 계좌. fm/fl: (경로, 달) 성장배수, fxl: (경로, 달+1) 환율 수준."""
    P, M = fm.shape
    cfg = ARM_CFG[arm]
    Vu = np.zeros(P); Bk = np.zeros(P); Bu = np.zeros(P)
    Vl = np.zeros(P); Blk = np.zeros(P); Blu = np.zeros(P)
    year_gain = np.zeros(P); tax_paid = np.zeros(P); harvested = np.zeros(P); wasted = np.zeros(P)
    n_step = np.zeros(P); n_skip = np.zeros(P); n_rebal = np.zeros(P)
    vals = np.zeros((P, M + 1)); expo = np.zeros((P, M))
    twr = np.zeros((P, M)) if want_twr else None

    for t in range(M):
        fx = fxl[:, t]
        if cal_month[t] == 0:
            year_gain = np.zeros(P)
        cash = np.full(P, monthly + (lump if t == 0 else 0.0))
        cash_usd = cash / fx
        tot = Vu + Vl
        if not cfg["leg"]:
            al = np.zeros(P)
        elif t == 0:
            al = TARGET_W * cash_usd                                        # 첫날 목돈도 목표 비중
        else:
            al = np.clip(TARGET_W * (tot + cash_usd) - Vl, 0.0, cash_usd)   # 적립금은 모자란 쪽부터
        Vl, Blk, Blu = _buy(Vl, Blk, Blu, al * fx, fx)
        Vu, Bk, Bu = _buy(Vu, Bk, Bu, (cash_usd - al) * fx, fx)

        if cal_month[t] == HARVEST_MONTH and t > 0:
            room = np.maximum(0.0, ALLOWANCE - year_gain)
            # ① 되돌림: 목표 초과분을 공제 한도 안에서만 팔아 시장을 산다 → 추가 세금 0
            if cfg["rebal"]:
                over = Vl - TARGET_W * (Vu + Vl)
                cap = _gross_usd_room_krw(Vl, Blk, room, fx, 0.0)
                g = np.minimum(np.maximum(over, 0.0), cap)
                Vl, Blk, Blu, cp, gain, tax = _sell(Vl, Blk, Blu, g, fx, year_gain)
                year_gain = year_gain + gain; tax_paid = tax_paid + tax; harvested = harvested + gain
                n_rebal += (g > 0)
                Vu, Bk, Bu = _buy(Vu, Bk, Bu, cp, fx)
                room = np.maximum(0.0, ALLOWANCE - year_gain)
            # ② 원가 올리기: 시장 보유분을 남은 공제만큼 팔았다 바로 되산다(배분·노출 변화 없음)
            if cfg["stepup"] is not None:
                if cfg["stepup"] == "krw":
                    g = _gross_usd_room_krw(Vu, Bk, room, fx, MIN_GAIN_RATE)
                else:
                    g = _gross_usd_room_usd(Vu, Bu, room, fx, MIN_GAIN_RATE)
                Vu, Bk, Bu, cp, gain, tax = _sell(Vu, Bk, Bu, g, fx, year_gain)
                year_gain = year_gain + gain; tax_paid = tax_paid + tax; harvested = harvested + gain
                n_step += (g > 0); n_skip += (g <= 0)
                wasted = wasted + np.maximum(0.0, room - np.maximum(gain, 0.0))
                Vu, Bk, Bu = _buy(Vu, Bk, Bu, cp, fx)

        tot = Vu + Vl
        expo[:, t] = np.where(tot > 0, (Vu + MULT * Vl) / _safe(tot), 1.0)
        base_krw = tot * fx
        Vu = Vu * fm[:, t]; Vl = Vl * fl[:, t]
        vals[:, t + 1] = (Vu + Vl) * fxl[:, t + 1]
        if want_twr:
            twr[:, t] = np.where(base_krw > 0, vals[:, t + 1] / _safe(base_krw) - 1.0, 0.0)

    fx_end = fxl[:, M]
    gross = (Vu + Vl) * fx_end
    w_end = np.where(gross > 0, (Vl * fx_end) / _safe(gross), 0.0)
    unreal = gross - (Bk + Blk)
    # 청산은 '다음 해 1월'(새 과세연도)에 한다고 본다 — 모든 팔에 같게 적용(부모 연구와 같다).
    tax_fin = CGT * np.maximum(0.0, unreal - ALLOWANCE)
    terminal = gross * (1.0 - SELL_COST) - tax_fin
    vals[:, 0] = lump + monthly
    peak = np.maximum.accumulate(vals, axis=1)
    mdd = np.min(vals / np.where(peak > 0, peak, 1.0) - 1.0, axis=1)
    out = {"terminal": terminal, "irr": irr_vec(terminal, M, lump, monthly), "mdd": mdd, "w_end": w_end,
           "tax": tax_paid + tax_fin, "tax_fin": tax_fin, "harvested": harvested, "wasted": wasted,
           "n_step": n_step, "n_skip": n_skip, "n_rebal": n_rebal, "exposure": expo.mean(axis=1),
           "fx_end": fx_end}
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
    """사전 등록 관문 5개(부모 연구와 같다) — 쌍둥이 base 대비."""
    k = L.kpi_pairs_verdict(compare(r, base), WIN_MIN, MED_MIN, P10_MIN)
    k["checks"]["mdd_within"] = bool(float(np.median(r["mdd"])) >= float(np.median(base["mdd"])) - MDD_GAP_MAX)
    k["checks"]["leg_drift"] = bool(float(np.median(r["w_end"])) <= LEG_W_MAX)
    k["pass"] = bool(all(k["checks"].values()))
    return k


def era_block(res: dict[str, dict]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for arm in ARMS:
        r = res[arm]
        twin = res[TWIN[arm]] if arm in TWIN else None
        blk = {"twin": TWIN.get(arm, "—"),
               "median_irr": float(np.nanmedian(r["irr"])), "median_mdd": float(np.median(r["mdd"])),
               "median_w_end": float(np.median(r["w_end"])), "median_exposure": float(np.median(r["exposure"])),
               "median_tax_krw": float(np.median(r["tax"])), "median_tax_fin_krw": float(np.median(r["tax_fin"])),
               "median_harvested_krw": float(np.median(r["harvested"])),
               "median_wasted_krw": float(np.median(r["wasted"])),
               "median_n_step": float(np.median(r["n_step"])), "median_n_skip": float(np.median(r["n_skip"])),
               "median_n_rebal": float(np.median(r["n_rebal"])),
               "median_terminal_krw": float(np.median(r["terminal"])),
               "median_fx_end": float(np.median(r["fx_end"]))}
        if twin is not None:
            blk["vs_twin"] = gate(r, twin)
            blk["terminal_diff_maxabs_krw"] = float(np.max(np.abs(r["terminal"] - twin["terminal"])))
        out[arm] = blk
    # 보조(사전 등록): 환율을 잊은 구현이 올바른 구현보다 얼마나 나쁜가
    out["C_STEPUP_USD"]["vs_A"] = L.kpi_pairs_verdict(compare(res["C_STEPUP_USD"], res["A_STEPUP_KRW"]),
                                                      WIN_MIN, MED_MIN, P10_MIN)
    return out


# =================================================================================================
# 본문
# =================================================================================================

def body(run):
    smoke = run.smoke
    months = 60 if smoke else HORIZON_MONTHS
    n_paths = 60 if smoke else N_PATHS
    block = 21 if smoke else BLOCK_DAYS

    def get_data():
        data = L.load_long_synthetic() if smoke else L.load_long_real()
        mkt = data["mkt"]
        rf = data["rf"].reindex(mkt.index).fillna(0.0)
        fx = load_fx_synthetic(mkt.index, mkt) if smoke else load_fx_real()
        fxr = fx_daily_return(mkt.index, fx)
        src = data["source"] + (" + 가짜 환율(스모크)" if smoke else
                                " + 원/달러 일별(FRED DEXKOUS, core.tax_fx.usdkrw_series)")
        return {"mkt": mkt, "rf": rf, "fxr": fxr, "source": src}

    data = run.stage("data", get_data)
    mkt, rf, fxr, source = data["mkt"], data["rf"], data["fxr"], data["source"]
    cal = np.arange(months) % 12          # 가상 역사: 첫 달을 1월로 본다

    def fx_levels(ff: np.ndarray, mode: str) -> np.ndarray:
        P, M = ff.shape
        if mode == "fix":
            return np.full((P, M + 1), FX0)
        out = np.empty((P, M + 1)); out[:, 0] = FX0
        out[:, 1:] = FX0 * np.cumprod(ff, axis=1)
        return out

    def do_era(lo: str, hi: str, seed_add: int):
        m, r, f, idx = era_arrays(mkt, rf, fxr, lo, hi)
        if len(m) < block * 4:
            return {"n_days": int(len(m)), "skipped": True}
        fm, fl, ff = bootstrap_monthly(m, r, f, months, n_paths, SEED + seed_add, block)
        fxl = {"real": fx_levels(ff, "real"), "fix": fx_levels(ff, "fix")}
        blk: dict[str, Any] = {
            "n_days": int(len(m)), "n_paths": int(n_paths), "months": int(months),
            "first_day": str(idx[0].date()), "last_day": str(idx[-1].date()),
            # 환율 진단(보고): 기간 전체 원화 약세폭, 시장과 환율 일 변화의 상관
            "fx_total_change": float(np.prod(1.0 + f) - 1.0),
            "fx_ann_change": float((np.prod(1.0 + f)) ** (252.0 / max(len(f), 1)) - 1.0),
            "corr_mkt_fx": float(np.corrcoef(m, f)[0, 1]) if len(m) > 3 else None,
        }
        for sc, (lump, monthly) in SCENARIOS.items():
            res = {}
            for arm in ARMS:
                run.check_time()
                res[arm] = simulate(fm, fl, fxl[ARM_CFG[arm]["fx"]], arm, cal, lump, monthly)
            blk[sc] = era_block(res)
        return blk

    eras: dict[str, Any] = {}
    for i, (name, (lo, hi)) in enumerate([*ERAS.items(), *REPORT_ERAS.items()]):
        eras[name] = run.stage(f"era_{name}", lambda lo=lo, hi=hi, i=i: do_era(lo, hi, 101 * (i + 1)))

    # 실제 역사(겹치지 않는 30년 구간 + 전체 한 경로, 판정 시나리오만) — 보고만
    def do_real():
        m, r, f, idx = era_arrays(mkt, rf, fxr, "1981-04-13", "2100-01-01")
        fm, fl, ff, per = real_monthly(m, r, f, idx)
        lump, monthly = SCENARIOS[JUDGE_SCENARIO]
        cm = np.array([p.month - 1 for p in per])
        fxl = {"real": fx_levels(ff[None, :], "real"), "fix": fx_levels(ff[None, :], "fix")}

        def one(sl: slice):
            sub = {k: fx_levels(ff[None, sl], k) for k in ("real", "fix")}
            return {a: simulate(fm[None, sl], fl[None, sl], sub[ARM_CFG[a]["fx"]], a, cm[sl], lump, monthly)
                    for a in ARMS}

        rows = []
        for s in range(0, len(fm) - months + 1, months):
            rr = one(slice(s, s + months))
            rows.append({"start": str(per[s]), "end": str(per[s + months - 1]),
                         **{a: {"irr": float(rr[a]["irr"][0]), "mdd": float(rr[a]["mdd"][0]),
                                "harvested": float(rr[a]["harvested"][0]), "tax": float(rr[a]["tax"][0]),
                                "wasted": float(rr[a]["wasted"][0])} for a in ARMS}})
            if len(rows) >= (2 if smoke else 99):
                break
        n = len(fm)
        fr = {a: simulate(fm[None, :n], fl[None, :n], fxl[ARM_CFG[a]["fx"]][:, :n + 1], a, cm[:n],
                          lump, monthly, want_twr=True) for a in ARMS}
        full = {"start": str(per[0]), "end": str(per[-1]), "months": int(n),
                "fx_end": float(fr["T_HOLD_REAL"]["fx_end"][0]),
                **{a: {"irr": float(fr[a]["irr"][0]), "mdd": float(fr[a]["mdd"][0]),
                       "harvested": float(fr[a]["harvested"][0]), "tax": float(fr[a]["tax"][0]),
                       "wasted": float(fr[a]["wasted"][0])} for a in ARMS}}
        act = {a: (fr[a]["twr"][0] - fr[TWIN[a]]["twr"][0]).tolist() for a in JUDGED}
        return {"windows": rows, "full": full, "active": act}

    real = run.stage("real", do_real)

    # 판정 — 판정 시나리오(S1)에서 두 시대(fx_a·fx_b) 모두 관문을 통과해야 한다
    power = rp.power_report(months / 12.0, len(JUDGED))
    verdicts: dict[str, str] = {}
    for arm in JUDGED:
        moved = [eras[e].get(JUDGE_SCENARIO, {}).get(arm, {}).get("terminal_diff_maxabs_krw") for e in ERAS]
        if not all(isinstance(x, (int, float)) and x > EVAL_TOL_KRW for x in moved):
            verdicts[arm] = "NOT_EVALUABLE"
            continue
        ok = [eras[e].get(JUDGE_SCENARIO, {}).get(arm, {}).get("vs_twin", {}).get("pass") for e in ERAS]
        if all(bool(x) for x in ok):
            verdicts[arm] = "STEPUP_HOLDS_WITH_FX"
        else:
            act = np.array(real["active"].get(arm, []), dtype=float)
            ir = None
            if len(act) > 2 and np.nanstd(act) > 0:
                ir = float(np.nanmean(act) / np.nanstd(act) * math.sqrt(12))
            verdicts[arm] = rp.classify_fail(ir, power)

    def diff(e: str, a: str, key: str = "vs_twin"):
        x = (eras[e].get(JUDGE_SCENARIO, {}).get(a, {}) or {}).get(key) or {}
        v = x.get("median_diff_irr")
        return v if isinstance(v, (int, float)) and math.isfinite(float(v)) else None

    def pp(v) -> str:
        return "—" if v is None else f"{v * 100:+.2f}%p"

    verdicts["stepup_realfx_vs_hold"] = (" / ".join(pp(diff(e, "A_STEPUP_KRW")) for e in ERAS) +
                                         " (실제 환율, 쌍둥이 대비 세후 IRR 중앙값, fx_a/fx_b)")
    verdicts["stepup_fixfx_vs_hold"] = (" / ".join(pp(diff(e, "B_STEPUP_FIX")) for e in ERAS) +
                                        " (환율 1,300원 고정 = v2 모델 재현)")
    verdicts["cost_of_ignoring_fx"] = (" / ".join(pp(diff(e, "C_STEPUP_USD", "vs_A")) for e in ERAS) +
                                       " (달러 이익률 구현 − 원화 이익률 구현)")
    verdicts["stepup_on_top_of_L20A"] = (" / ".join(pp(diff(e, "D_L20A_STEPUP")) for e in ERAS) +
                                         " (L20A 대비)")
    a_f = [diff(e, "A_STEPUP_KRW") for e in ERAS]
    b_f = [diff(e, "B_STEPUP_FIX") for e in ERAS]
    if all(isinstance(x, float) for x in a_f + b_f):
        d = [x - y for x, y in zip(a_f, b_f)]
        verdicts["fx_effect_on_stepup"] = ("환율이 이득을 " + ("키운다" if min(d) > 0 else
                                           "줄인다" if max(d) < 0 else "시대마다 반대로 바꾼다") +
                                           " (" + " / ".join(pp(x) for x in d) + ", 실제 − 고정)")
    else:
        verdicts["fx_effect_on_stepup"] = "측정 불가"

    result = {"id": "frontier-stepup-fx-v1", "rules_version": RULES_VERSION, "smoke": smoke, "source": source,
              "scenario": {"scenarios": {k: list(v) for k, v in SCENARIOS.items()},
                           "judge_scenario": JUDGE_SCENARIO, "months": months, "n_paths": n_paths,
                           "block_days": block, "target_leg_weight": TARGET_W, "fx_start": FX0,
                           "harvest_month": HARVEST_MONTH + 1, "min_gain_rate": MIN_GAIN_RATE},
              "thresholds": {"win_min": WIN_MIN, "median_irr_min": MED_MIN, "p10_irr_min": P10_MIN,
                             "mdd_gap_max": MDD_GAP_MAX, "leg_w_max": LEG_W_MAX,
                             "eval_tol_krw": EVAL_TOL_KRW},
              "power": power, "eras": L.rnd(eras), "real_history": L.rnd(real["windows"]),
              "real_full": L.rnd(real["full"]), "verdicts": verdicts}
    return result, report(result)


def man(x) -> str:
    """원 → '…만 원'."""
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
    v = r["verdicts"]
    lines = [f"# 원가 올리기에 환율을 넣으면 — 원화 과세 기준 (frontier-stepup-fx-v1/{RULES_VERSION.split('/')[-1]})", "",
             "한국 해외주식 양도세는 **원화 기준**이다: 양도차익 = 양도가액 × 매도일 환율 − 취득가액 × 매수일 환율.",
             "그래서 환율은 과세 대상의 크기와 부호를 함께 바꾼다. frontier-tax-allowance-v2 는 환율을 1,300원으로 **고정**해 두고",
             "'연 250만 원 공제로 취득원가를 올리면 위험을 늘리지 않고 세후 수익이 는다'는 결과를 얻었다. 이 연구는 그 결과를",
             "**환율을 실제로 넣어** 다시 잰다(원/달러 1981-04~, 시장 수익과 같은 날짜 덩어리로 함께 부트스트랩).", "",
             "**판정:** " + " · ".join(f"{k} **{v[k]}**" for k in JUDGED), "",
             f"- 실제 환율 · 원화 이익률(주 판정): **{v.get('stepup_realfx_vs_hold')}**",
             f"- 환율 1,300원 고정(v2 모델 재현): {v.get('stepup_fixfx_vs_hold')}",
             f"- 환율의 몫: **{v.get('fx_effect_on_stepup')}**",
             f"- 환율을 잊은 구현의 값: {v.get('cost_of_ignoring_fx')}",
             f"- L20A 위에 덧붙이면: {v.get('stepup_on_top_of_L20A')}", "",
             "통과는 '전진 원장 후보'일 뿐 엔진 채택이 아니다. 엔진은 바뀌지 않았다.", "",
             "## 규칙 (결과를 보기 전에 고정)", "",
             f"- 계좌(판정): {js} = 처음 {SCENARIOS[js][0]:,.0f} 원 + 매달 {SCENARIOS[js][1]:,.0f} 원. 매수·매도마다 0.15%(수수료 0.1% + 환전 0.05%).",
             f"  달러 자산을 들고, 취득가액은 **원화 이동평균**. 양도세 22% × max(0, 그해 실현 원화차익 − 250만 원)을 판 즉시 현금에서 뺀다.",
             f"  환율은 {FX0:,.0f}원에서 출발한다. 청산은 **다음 해 1월**(새 과세연도)에 한다고 본다 — 모든 팔에 같게 적용.",
             f"- 원가 올리기는 매년 {sc['harvest_month']}월에만, 이익률이 {MIN_GAIN_RATE:.0%} 이상일 때만 한다. 한 해 안의 순서는 늘 '되돌림 → 원가 올리기'다.",
             f"- 다리(L20A 팔): 필터 없는 고정 2배(일일 리셋, 차입 가산 연 1% + 보수 연 0.9%), 목표 비중 {TARGET_W:.0%}. 가격 신호는 쓰지 않는다.",
             "- 팔(7개): " + " · ".join(f"**{a}**={ARM_NOTE[a]}" for a in ARMS),
             "- 쌍둥이 비교: " + " · ".join(f"{a}↔{TWIN[a]}" for a in JUDGED) + " (같은 환율·같은 배분끼리 비교해 세금 효과만 떼어 본다).",
             f"- 통과(STEPUP_HOLDS_WITH_FX) ⇔ **두 시대 모두** ① 쌍둥이보다 많이 남은 경로 ≥ {WIN_MIN:.0%} ② 세후 IRR 차이 중앙값 ≥ {MED_MIN * 100:+.2f}%p "
             f"③ 10분위 ≥ {P10_MIN * 100:+.2f}%p ④ 낙폭 중앙값이 쌍둥이보다 {MDD_GAP_MAX * 100:.1f}%p 넘게 나쁘지 않음 ⑤ 말기 다리 비중 중앙값 ≤ {LEG_W_MAX:.0%}.",
             "  문턱·관문은 부모 연구(frontier-tax-allowance-v2)의 것을 **한 글자도 바꾸지 않고** 그대로 썼다 — 전이 검사이기 때문이다.",
             f"- 가상 역사: 원형 블록 부트스트랩(블록 {sc['block_days']}거래일), 시대마다 경로 {sc['n_paths']}개, {sc['months']}달.",
             "  시대 = fx_a(1981-04~2002-12 일자) · fx_b(2003-01~2024-09 일자). 한 경로 안에서 **시장·금리·환율이 같은 날짜 덩어리**를 쓴다(위기 때 환율 움직임 보존).",
             "  fx_full(두 시대 합침)과 실제 역사 한 경로는 **보고만**. 2024-10 이후는 떼어 둔 소진 구간이라 쓰지 않는다.",
             "- 계좌 크기 3종(S1 판정 / S2 목돈 0+월 10만 / S3 1억+월 100만)은 **보고만** — 공제는 정액이라 계좌가 커지면 효과가 묽어진다.",
             f"- 판정 팔 {len(JUDGED)}개뿐이고 문턱·시나리오·공제 사용 순서는 결과를 보기 전에 고정했다. **가격 규칙이 한 줄도 없다**(격자 확장이 아니다).",
             "  겹침 공시: 1927~2024 가격과 공제 한도 되돌림(L20A)은 여러 연구가 이미 봤다(frontier-lev-rebal-v1 A4_ALLOW·lev-weight-frontier-v1 w20·frontier-tax-allowance-v1/v2).",
             "  새 자료는 **원/달러 일별(1981-04~)을 시장과 함께 부트스트랩에 넣은 것**이고, 새 메커니즘은 **원화 과세 기준**이다.", "",
             "- " + rp.power_line(r["power"]),
             "  (주의: IR 기반 검정력은 **세전 수익 경로**에 대한 것이다. 이 연구의 효과는 세전 수익이 아니라 세금에 있으므로 낸 세금·원가 올린 이익·버린 공제 열을 함께 읽어야 한다.)", "",
             f"자료: {r['source']}", ""]

    for name in [*ERAS, *REPORT_ERAS]:
        b = e.get(name, {})
        if not b or b.get("skipped"):
            lines += [f"## {name} — 자료 부족으로 건너뜀", ""]
            continue
        tag = " (보고만)" if name in REPORT_ERAS else ""
        lines += [f"### {name}{tag} 환율 진단 — {b.get('first_day')}~{b.get('last_day')}, {b.get('n_days')}일: "
                  f"기간 전체 원화 변화 {L.pct(b.get('fx_total_change'), True)} · 연 {L.pct(b.get('fx_ann_change'), True, 2)} · "
                  f"시장·환율 일 변화 상관 {num(b.get('corr_mkt_fx'), 3)}", ""]
        for scn in SCENARIOS:
            blk = b.get(scn, {})
            if not blk:
                continue
            mark = "판정" if scn == js and name in ERAS else "보고만"
            lump, monthly = SCENARIOS[scn]
            lines += [f"## {name}{tag} · {scn}(목돈 {lump / 1e4:,.0f}만 + 월 {monthly / 1e4:,.0f}만, {mark}) — 가상 역사 {b.get('n_paths')}개, {b.get('months')}달", "",
                      "| 팔 | 쌍둥이 | 이긴 비율 | IRR 차이 중앙/10분위 | 세후 IRR 중앙 | 계좌 낙폭 중앙 | 말기 다리 비중 | 원가 올린 이익 | 버린 공제 | 올린 해/못한 해 | 청산 세금 중앙 | 말기 환율 | 관문 |",
                      "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
            for a in ARMS:
                x = blk.get(a, {})
                vt = x.get("vs_twin") or {}
                ck = "—" if not vt else (",".join(k for k, z in (vt.get("checks") or {}).items() if not z) or "모두 충족")
                lines.append(
                    f"| {a} | {x.get('twin')} | {L.pct(vt.get('share_win')) if vt else '—'} | "
                    f"{L.pct(vt.get('median_diff_irr'), True, 2) if vt else '—'} / {L.pct(vt.get('p10_diff_irr'), True, 2) if vt else '—'} | "
                    f"{L.pct(x.get('median_irr'))} | {L.pct(x.get('median_mdd'), True)} | {L.pct(x.get('median_w_end'))} | "
                    f"{man(x.get('median_harvested_krw'))} | {man(x.get('median_wasted_krw'))} | "
                    f"{num(x.get('median_n_step'), 0)}/{num(x.get('median_n_skip'), 0)} | "
                    f"{man(x.get('median_tax_fin_krw'))} | {num(x.get('median_fx_end'), 0)}원 | {ck} |")
            cu = (blk.get("C_STEPUP_USD") or {}).get("vs_A") or {}
            if cu:
                lines += ["", "환율을 잊은 구현(C) − 올바른 구현(A): "
                          f"IRR 차이 중앙 {L.pct(cu.get('median_diff_irr'), True, 2)} · 이긴 비율 {L.pct(cu.get('share_win'))}"]
            lines.append("")

    lines += ["## 실제 역사(겹치지 않는 30년 구간 · 보고만)", "",
              "| 구간 | " + " | ".join(ARMS) + " |", "|---|" + "---|" * len(ARMS)]
    for w in r["real_history"]:
        lines.append(f"| {w['start']}~{w['end']} | " + " | ".join(L.pct(w[a]["irr"]) for a in ARMS) + " |")
    f = r["real_full"]
    lines += ["", f"전체 한 경로({f['start']}~{f['end']}, {f['months']}달, 말기 환율 {num(f.get('fx_end'), 0)}원): " +
              " · ".join(f"{a} IRR {L.pct(f[a]['irr'])}/낙폭 {L.pct(f[a]['mdd'], True)}/원가 올린 이익 {man(f[a].get('harvested'))}"
                         for a in ARMS), "",
              "## 주의", "",
              "- 핵심 가정: 한국 해외주식 양도소득세에는 **wash-sale 규정이 없다** — 팔았다 같은 날 되사도 취득원가가 새로 잡힌다. 세법이 바뀌면 결론은 무효다.",
              "- 팔았다 되사기를 **같은 날 같은 가격·같은 환율**로 본다. 비용은 왕복 0.3% 만 뗐다.",
              "- 취득원가는 **원화 이동평균법**이다(증권사에 따라 다를 수 있다). 환전 시점·환전 수수료 구조도 증권사마다 다르다.",
              "- 환율 자료는 1981-04 부터다. 그 전(브레튼우즈·고정환율기)은 넣지 않았다 — 가상 역사의 원재료가 그만큼 짧다(한 시대 약 21년).",
              f"- 환율은 **수준이 아니라 변화율**만 쓴다: 가상 역사와 실제 역사 칸 모두 {FX0:,.0f}원에서 출발해 그 구간의 실제 변화를 따라간다(모든 팔에 같게 적용).",
              "- 가상 역사는 블록을 섞은 표본이지만 원재료는 **같은 미국 시장 + 같은 원/달러 역사**다. 완전히 새로운 정보는 아니다.",
              "- 계좌 낙폭은 **월말 원화 가치** 기준이라 달 안의 더 깊은 낙폭은 빠진다(모든 팔에 같게 적용). 환율 변동이 낙폭에 섞여 있다.",
              "- 다리는 **합성 2배**다. 실제 상품(SSO)·정밀 세금은 engine-candidate-v1 이 2006~2024 한 역사에서만 확인했다.",
              "- 금융소득종합과세·건강보험료·배당 원천징수는 넣지 않았다. 세금은 '판 즉시 차감'이라 실제(다음 해 5월 납부)보다 약간 불리하다.",
              "- 효과 크기가 작다(부모 연구 +0.1%p 급). liquidation-accounting-impact-v1 이 잰 회계 관례 차이가 ±0.04%p 였으므로, 부호가 유지되는지를 먼저 읽어야 한다.",
              "- 통과해도 **전진 원장에 올릴 후보**일 뿐이다. 투자 조언이 아니다."]
    return "\n".join(lines)


if __name__ == "__main__":
    runner = L.Runner(RULES_VERSION)
    raise SystemExit(runner.run(body))
