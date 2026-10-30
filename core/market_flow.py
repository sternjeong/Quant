"""시장 간 자금 흐름 모니터 — 어느 시장이 강하고 약한지, 시장끼리 얼마나 같이 움직이는지, 주도주는 누구인지.

설계 근거(2026-10-30, 사용자 요청: "기술주가 떨어질 때 다른 시장으로 돈이 이동하는지 보고 싶다"):
- 강도는 기존 `core.sector_strength` 와 같은 IBD 가중 ROC(63/126/189/252거래일)를 쓴다 — 새 지표를 만들지 않고
  이미 문서화된 정의(MARKET_REGIME_SECTOR_STRENGTH_SPEC.md)를 재사용한다.
- 로테이션 4분면은 RRG(Relative Rotation Graph) 방식의 단순판이다: 상대강도 비율(자산/SPY)이 자기 63일 평균
  위인가(RS-Ratio), 그 비율이 10거래일 전보다 올랐는가(RS-Momentum).
- "자금 이동"은 펀드 유출입 데이터가 아니다(무료 소스에 없음). 20일 초과수익과 거래대금 증가율을 합친 가격·거래대금
  대리지표이며, 화면에도 그렇게 표시한다.
- 사용자의 가설("한 시장에서 돈이 빠지면 다른 시장으로 들어온다")은 `conditional_forward_excess` 로 과거 자료에서
  직접 센다. 표본이 겹치지 않는 에피소드만 세고, 자산 수만큼 검정하므로 Bonferroni 보정 후에도 남는지 따로 표시한다.
  R&D 결과(theme-rotation-v1·regime-rnd-v1·leader-catch 계열)에서 로테이션 신호가 세후로 SPY 를 이기지 못했으므로,
  이 모듈의 출력은 매매 신호가 아니라 관측치다. 주문·추천·챔피언 규칙과 연결하지 않는다.

순수 계산 함수는 가격 DataFrame 만 받아 네트워크 없이 테스트할 수 있다. 가격 조회는 `load_universe` 한 곳에서만 한다.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

import numpy as np
import pandas as pd

from core.indicators import roc

BENCHMARK = "SPY"

# 그룹 -> {티커: 표시 이름}. 프리셋이라 시장을 더하려면 항목만 추가하면 된다.
MARKET_UNIVERSE: dict[str, dict[str, str]] = {
    "미국 지수": {"SPY": "S&P500", "QQQ": "나스닥100", "IWM": "미국 소형주", "DIA": "다우"},
    "미국 섹터": {
        "XLK": "기술", "SMH": "반도체", "XLC": "커뮤니케이션", "XLY": "임의소비재", "XLF": "금융",
        "XLV": "헬스케어", "XLI": "산업재", "XLE": "에너지", "XLB": "소재", "XLP": "필수소비재",
        "XLU": "유틸리티", "XLRE": "부동산",
    },
    "해외 주식": {
        "EFA": "선진국(미국 제외)", "VGK": "유럽", "EWJ": "일본", "EEM": "신흥국", "EWY": "한국",
        "FXI": "중국", "INDA": "인도", "EWT": "대만",
    },
    "채권": {"TLT": "미국 장기국채", "IEF": "미국 중기국채", "LQD": "투자등급 회사채", "HYG": "하이일드"},
    "실물·통화·암호화폐": {
        "GLD": "금", "SLV": "은", "USO": "원유", "DBC": "원자재 종합", "UUP": "달러 지수", "BTC-USD": "비트코인",
    },
}

LOOKBACK_DAYS = 800  # 252거래일 ROC + 추세 비교 + 여유
LONG_LOOKBACK_DAYS = 365 * 16  # 조건부 연구용 장기 이력

ROC_WEIGHTS: list[tuple[int, float]] = [(63, 0.4), (126, 0.2), (189, 0.2), (252, 0.2)]

QUADRANT_LEADING = "주도"
QUADRANT_WEAKENING = "약화"
QUADRANT_LAGGING = "부진"
QUADRANT_IMPROVING = "개선"

RS_AVG_WINDOW = 63
RS_MOM_LAG = 10
FLOW_RET_WINDOW = 20
FLOW_VOL_SHORT = 20
FLOW_VOL_LONG = 120

MIN_EPISODES_FOR_STAT = 5  # 이보다 적은 에피소드는 통계 없이 표본 수만 보여 준다


def all_tickers() -> list[str]:
    return [t for group in MARKET_UNIVERSE.values() for t in group]


def ticker_names() -> dict[str, str]:
    return {t: n for group in MARKET_UNIVERSE.values() for t, n in group.items()}


def ticker_groups() -> dict[str, str]:
    return {t: g for g, members in MARKET_UNIVERSE.items() for t in members}


# --------------------------------------------------------------------------- 데이터

ET = ZoneInfo("America/New_York")
US_CLOSE_SETTLED = (16, 15)  # 미 동부 16:15 이후에만 그날 일봉을 완성된 것으로 본다(hypothesis_shadow 와 같은 규칙)


def last_complete_date(now_et: Optional[datetime] = None) -> date:
    """마감이 확정된 가장 최근 미국 거래일 후보(주말·휴장은 거르지 않고 달력상 상한만 준다)."""
    now_et = now_et or datetime.now(ET)
    today = now_et.date()
    if now_et.weekday() < 5 and (now_et.hour, now_et.minute) < US_CLOSE_SETTLED:
        return today - timedelta(days=1)
    return today


def load_universe(
    tickers: Optional[list[str]] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    loader=None,
    now_et: Optional[datetime] = None,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """종가·거래량 표를 만든다. 반환: (close, volume, 못 받은 티커).

    암호화폐처럼 주말에도 거래되는 자산이 있어, 기준 자산(SPY)의 거래일에 맞춰 정렬한다. 장중이라 미완성인
    오늘 봉은 모든 자산에서 뺀다. loader·now_et 는 테스트에서 외부 의존을 대신하기 위한 인자다.
    """
    tickers = tickers or all_tickers()
    start = start or (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    if loader is None:
        from core.market_data import get_multiple_price_history as loader  # noqa: PLC0415

    histories = loader(tickers, start=start, end=end, interval="1d")
    closes: dict[str, pd.Series] = {}
    volumes: dict[str, pd.Series] = {}
    missing: list[str] = []
    for t in tickers:
        df = histories.get(t)
        if df is None or df.empty or "Close" not in df.columns:
            missing.append(t)
            continue
        close = df["Close"].dropna()
        if close.empty:
            missing.append(t)
            continue
        closes[t] = close
        if "Volume" in df.columns:
            volumes[t] = df["Volume"].reindex(close.index)

    cutoff = pd.Timestamp(last_complete_date(now_et))
    close_df = pd.DataFrame(closes).sort_index().loc[:cutoff]
    volume_df = pd.DataFrame(volumes).sort_index().loc[:cutoff]
    if BENCHMARK in close_df.columns:
        trading_days = close_df[BENCHMARK].dropna().index
        close_df = close_df.reindex(trading_days).ffill(limit=3)
        volume_df = volume_df.reindex(trading_days)
    return close_df, volume_df, missing


# --------------------------------------------------------------------------- 강도·로테이션

def strength_factor(close: pd.Series) -> Optional[float]:
    """IBD 가중 ROC. 이력이 짧으면 가능한 구간만 가중치를 다시 100% 로 맞춰 쓴다(sector_strength 와 같은 규칙)."""
    s = close.dropna()
    usable = [(w, wt) for w, wt in ROC_WEIGHTS if len(s) >= w + 1]
    if not usable:
        return None
    total_weight = sum(wt for _, wt in usable)
    out = 0.0
    for window, weight in usable:
        r = roc(s, window).dropna()
        if r.empty:
            return None
        out += float(r.iloc[-1]) * (weight / total_weight)
    return out


def rs_ratio_momentum(close: pd.Series, benchmark: pd.Series) -> Optional[pd.DataFrame]:
    """RRG 단순판. 반환 컬럼: rs_ratio(100 기준), rs_momentum(100 기준). 이력이 모자라면 None."""
    aligned = pd.concat([close, benchmark], axis=1, join="inner").dropna()
    if len(aligned) < RS_AVG_WINDOW + RS_MOM_LAG + 1:
        return None
    ratio = aligned.iloc[:, 0] / aligned.iloc[:, 1]
    rs_ratio = 100 * ratio / ratio.rolling(RS_AVG_WINDOW).mean()
    rs_mom = 100 * rs_ratio / rs_ratio.shift(RS_MOM_LAG)
    out = pd.DataFrame({"rs_ratio": rs_ratio, "rs_momentum": rs_mom}).dropna()
    return out if not out.empty else None


def quadrant(rs_ratio: float, rs_momentum: float) -> str:
    if rs_ratio >= 100:
        return QUADRANT_LEADING if rs_momentum >= 100 else QUADRANT_WEAKENING
    return QUADRANT_IMPROVING if rs_momentum >= 100 else QUADRANT_LAGGING


def _zscore(s: pd.Series) -> pd.Series:
    sd = s.std(ddof=0)
    if not np.isfinite(sd) or sd == 0:
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / sd


def compute_market_table(close: pd.DataFrame, volume: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """시장별 한 줄 요약: 수익률, IBD 강도 점수, RRG 4분면, 자금 이동 대리지표.

    flow_score = z(20일 초과수익 vs SPY) + z(거래대금 증가율). 거래량이 없는 자산(지수 등)은 앞 항만 쓴다.
    양수 = 돈이 들어오는 쪽, 음수 = 빠지는 쪽으로 읽는 **대리지표**이며 실제 펀드 유입이 아니다.
    """
    if BENCHMARK not in close.columns:
        return pd.DataFrame()
    bench = close[BENCHMARK].dropna()
    names, groups = ticker_names(), ticker_groups()
    rows = []
    for t in close.columns:
        s = close[t].dropna()
        factor = strength_factor(s)
        if factor is None:
            continue
        rrg = rs_ratio_momentum(s, bench)
        rs_ratio = float(rrg["rs_ratio"].iloc[-1]) if rrg is not None else None
        rs_mom = float(rrg["rs_momentum"].iloc[-1]) if rrg is not None else None
        rel_20 = None
        if len(s) > FLOW_RET_WINDOW and len(bench) > FLOW_RET_WINDOW:
            both = pd.concat([s, bench], axis=1, join="inner").dropna()
            if len(both) > FLOW_RET_WINDOW:
                r = both.iloc[-1] / both.iloc[-1 - FLOW_RET_WINDOW] - 1
                rel_20 = float((r.iloc[0] - r.iloc[1]) * 100)
        vol_ratio = None
        if volume is not None and t in volume.columns:
            dv = (close[t] * volume[t]).dropna()
            dv = dv[dv > 0]
            if len(dv) >= FLOW_VOL_LONG:
                vol_ratio = float(dv.tail(FLOW_VOL_SHORT).mean() / dv.tail(FLOW_VOL_LONG).mean() - 1) * 100
        peak = s.tail(252).max()
        rows.append({
            "ticker": t, "name": names.get(t, t), "group": groups.get(t, ""),
            "return_1m": _last_roc(s, 21), "return_3m": _last_roc(s, 63),
            "return_6m": _last_roc(s, 126), "return_12m": _last_roc(s, 252),
            "strength_factor": factor, "rel_20d": rel_20, "dollar_vol_change": vol_ratio,
            "drawdown_52w": float((s.iloc[-1] / peak - 1) * 100) if peak and peak > 0 else None,
            "rs_ratio": rs_ratio, "rs_momentum": rs_mom,
            "quadrant": quadrant(rs_ratio, rs_mom) if rs_ratio is not None else None,
        })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["rs_score"] = df["strength_factor"].rank(pct=True) * 100
    z_rel = _zscore(df["rel_20d"].astype(float)) if df["rel_20d"].notna().any() else pd.Series(0.0, index=df.index)
    z_vol = _zscore(df["dollar_vol_change"].astype(float)) if df["dollar_vol_change"].notna().any() else pd.Series(0.0, index=df.index)
    df["flow_score"] = z_rel.fillna(0.0) + z_vol.fillna(0.0)
    return df.sort_values("rs_score", ascending=False).reset_index(drop=True)


def _last_roc(s: pd.Series, window: int) -> Optional[float]:
    if len(s) <= window:
        return None
    return float(roc(s, window).iloc[-1])


def rrg_tails(close: pd.DataFrame, tickers: list[str], weeks: int = 8) -> dict[str, pd.DataFrame]:
    """선택한 자산들의 최근 `weeks` 주 RRG 궤적(주 단위 샘플). 꼬리가 시계방향으로 도는지 눈으로 본다."""
    if BENCHMARK not in close.columns:
        return {}
    bench = close[BENCHMARK].dropna()
    out: dict[str, pd.DataFrame] = {}
    for t in tickers:
        if t not in close.columns or t == BENCHMARK:
            continue
        rrg = rs_ratio_momentum(close[t].dropna(), bench)
        if rrg is None:
            continue
        out[t] = rrg.iloc[::-1].iloc[::5].iloc[:weeks + 1].iloc[::-1]
    return out


# --------------------------------------------------------------------------- 상관

def log_returns(close: pd.DataFrame) -> pd.DataFrame:
    return np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan)


def correlation_matrix(close: pd.DataFrame, window: int) -> pd.DataFrame:
    """최근 `window` 거래일 일간 로그수익률의 상관행렬. 관측치가 window 의 70% 미만인 자산은 뺀다."""
    rets = log_returns(close).tail(window)
    keep = [c for c in rets.columns if rets[c].notna().sum() >= int(window * 0.7)]
    return rets[keep].corr(min_periods=int(window * 0.7))


def correlation_shift(close: pd.DataFrame, short: int = 60, long: int = 252) -> pd.DataFrame:
    """짧은 창 상관 − 긴 창 상관. 양수 = 요즘 더 같이 움직임, 음수 = 따로 움직임."""
    c_short, c_long = correlation_matrix(close, short), correlation_matrix(close, long)
    cols = [c for c in c_short.columns if c in c_long.columns]
    return (c_short.loc[cols, cols] - c_long.loc[cols, cols])


def top_correlation_moves(close: pd.DataFrame, short: int = 60, long: int = 252, n: int = 10) -> pd.DataFrame:
    """상관이 가장 크게 바뀐 자산 쌍. 컬럼: a, b, corr_short, corr_long, change."""
    c_short, c_long = correlation_matrix(close, short), correlation_matrix(close, long)
    cols = [c for c in c_short.columns if c in c_long.columns]
    rows = []
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            cs, cl = c_short.loc[a, b], c_long.loc[a, b]
            if np.isnan(cs) or np.isnan(cl):
                continue
            rows.append({"a": a, "b": b, "corr_short": float(cs), "corr_long": float(cl), "change": float(cs - cl)})
    if not rows:
        return pd.DataFrame(columns=["a", "b", "corr_short", "corr_long", "change"])
    df = pd.DataFrame(rows)
    return df.reindex(df["change"].abs().sort_values(ascending=False).index).head(n).reset_index(drop=True)


def rolling_pair_correlation(close: pd.DataFrame, a: str, b: str, window: int = 60) -> pd.Series:
    rets = log_returns(close)[[a, b]].dropna()
    return rets[a].rolling(window).corr(rets[b]).dropna()


def diversifier_candidates(table: pd.DataFrame, close: pd.DataFrame, weak: str, window: int = 60) -> pd.DataFrame:
    """`weak` 자산이 약할 때 눈여겨볼 곳: 최근 상관이 낮거나 음수이면서 상대강도가 센 자산.

    candidate_score = rs_score(0~100) 에서 상관 × 50 을 뺀 값. 가중치는 임의의 휴리스틱이며 예측력은 검증되지 않았다 —
    그래서 이름도 '후보'다. 예측력은 `conditional_forward_excess` 로 따로 센다.
    """
    corr = correlation_matrix(close, window)
    if weak not in corr.columns or table.empty:
        return pd.DataFrame()
    out = table[table["ticker"] != weak].copy()
    out["corr_to_weak"] = out["ticker"].map(corr[weak])
    out = out.dropna(subset=["corr_to_weak"])
    out["candidate_score"] = out["rs_score"] - out["corr_to_weak"] * 50
    return out.sort_values("candidate_score", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------- 조건부 연구

def _normal_two_sided_p(t: float) -> float:
    return math.erfc(abs(t) / math.sqrt(2))


def conditional_forward_excess(
    close: pd.DataFrame,
    source: str,
    benchmark: str = BENCHMARK,
    trigger_window: int = 20,
    horizon: int = 20,
    quantile: float = 0.10,
    min_history: int = 504,
) -> pd.DataFrame:
    """"`source` 가 크게 빠진 뒤 다른 시장은 어떻게 됐나"를 과거 자료에서 센다.

    트리거: `source` 의 직전 `trigger_window` 거래일 수익률이, 그날까지의 **확장 분포**(미래 정보 없음) 하위 `quantile` 이하.
    효과: 트리거일 뒤 `horizon` 거래일 동안 각 자산의 (자산 − benchmark) 초과수익에서, 같은 자산의 무조건 평균 초과수익을 뺀 값.
    에피소드는 직전 에피소드와 `horizon` 거래일 이상 떨어진 것만 센다(겹치는 창은 같은 사건을 여러 번 세므로).

    반환 컬럼: ticker, episodes, mean_excess(%p), t_stat, p_value, significant_raw, significant_bonferroni, hit_rate.
    attrs: episode_dates, n_tests, samples(자산별 에피소드 값).
    에피소드가 MIN_EPISODES_FOR_STAT 미만이면 통계는 NaN 이고 표본 수만 남는다.
    """
    if source not in close.columns or benchmark not in close.columns:
        return pd.DataFrame()
    px = close.dropna(subset=[source, benchmark])
    if len(px) < min_history:
        return pd.DataFrame()

    src_ret = px[source] / px[source].shift(trigger_window) - 1
    threshold = src_ret.expanding(min_periods=min_history // 2).quantile(quantile)
    trigger = (src_ret <= threshold) & threshold.notna()

    episode_dates: list[pd.Timestamp] = []
    last_pos = -10**9
    for pos, (dt, hit) in enumerate(trigger.items()):
        if hit and pos - last_pos >= horizon:
            episode_dates.append(dt)
            last_pos = pos
    if not episode_dates:
        return pd.DataFrame()

    fwd = px.shift(-horizon) / px - 1
    bench_fwd = fwd[benchmark]
    others = [c for c in px.columns if c not in (source, benchmark)]
    # 요약 지표는 SPY 대비 초과수익이라, 자산별 무조건 평균과 비교한다.
    rows = []
    samples: dict[str, pd.Series] = {}
    n_tests = max(len(others), 1)
    for t in others:
        excess = (fwd[t] - bench_fwd) * 100
        baseline = excess.mean(skipna=True)
        sample = excess.reindex(episode_dates).dropna()
        n = len(sample)
        row = {"ticker": t, "episodes": n, "mean_excess": np.nan, "t_stat": np.nan, "p_value": np.nan,
               "significant_raw": False, "significant_bonferroni": False, "hit_rate": np.nan}
        if n >= MIN_EPISODES_FOR_STAT:
            diff = sample - baseline
            samples[t] = diff
            sd = diff.std(ddof=1)
            if sd and np.isfinite(sd) and sd > 0:
                t_stat = float(diff.mean() / (sd / math.sqrt(n)))
                p = _normal_two_sided_p(t_stat)
                row.update({
                    "mean_excess": float(diff.mean()), "t_stat": t_stat, "p_value": p,
                    "significant_raw": p < 0.05, "significant_bonferroni": p < 0.05 / n_tests,
                    "hit_rate": float((diff > 0).mean() * 100),
                })
        rows.append(row)
    out = pd.DataFrame(rows)
    out.attrs["episode_dates"] = episode_dates
    out.attrs["n_tests"] = n_tests
    out.attrs["samples"] = samples  # 자산별 에피소드 초과수익(%p, 평소 평균 차감) — 하위 구간 점검용
    return out.sort_values("mean_excess", ascending=False, na_position="last").reset_index(drop=True)


# --------------------------------------------------------------------------- 주도주

def price_leaders(candidates: list[str], histories: dict[str, pd.DataFrame], top_n: int = 5) -> pd.DataFrame:
    """테마 후보 종목 중 가격 기준 주도주 순위: IBD 강도 점수. 시가총액(대표주)과 별개로 '지금 가장 센 종목'을 뽑는다."""
    rows = []
    for t in candidates:
        df = histories.get(t)
        if df is None or df.empty or "Close" not in df.columns:
            continue
        s = df["Close"].dropna()
        factor = strength_factor(s)
        if factor is None:
            continue
        rows.append({
            "ticker": t, "strength_factor": factor,
            "return_1m": _last_roc(s, 21), "return_3m": _last_roc(s, 63), "return_12m": _last_roc(s, 252),
        })
    if not rows:
        return pd.DataFrame(columns=["ticker", "strength_factor", "return_1m", "return_3m", "return_12m", "rs_score"])
    df = pd.DataFrame(rows)
    df["rs_score"] = df["strength_factor"].rank(pct=True) * 100
    return df.sort_values("strength_factor", ascending=False).head(top_n).reset_index(drop=True)


def normalized_returns(close: pd.DataFrame, tickers: list[str], days: int) -> pd.DataFrame:
    """최근 `days` 거래일의 누적수익률(%) — 시작일 0%."""
    cols = [t for t in tickers if t in close.columns]
    sub = close[cols].dropna(how="all").tail(days + 1).ffill().dropna()
    if sub.empty:
        return pd.DataFrame()
    return (sub / sub.iloc[0] - 1) * 100


# --------------------------------------------------------------------------- 시장별 주도주 후보

# 섹터 ETF 는 core.sector_leaders 의 테마 후보(S&P500 구성종목·니치 프리셋)를 그대로 쓴다. 아래는 그 밖의 시장 대표 후보로,
# 구성이 바뀌면 이 프리셋만 고치면 된다. 채권은 개별 종목 주도주 개념이 없어 비워 둔다.
LEADER_PRESETS: dict[str, list[str]] = {
    "SPY": ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "AVGO", "BRK-B", "JPM", "LLY"],
    "QQQ": ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "AVGO", "TSLA", "COST", "NFLX"],
    "DIA": ["GS", "MSFT", "HD", "CAT", "UNH", "V", "AMGN", "MCD", "JPM", "TRV"],
    "IWM": ["SMCI", "FTAI", "IBKR", "SFM", "RKLB", "CVLT", "ONTO", "ANF", "AIT", "MLI"],
    "EFA": ["ASML", "SAP", "NVO", "AZN", "SHEL", "TM", "SONY", "NVS", "HSBC", "UL"],
    "VGK": ["ASML", "SAP", "NVO", "AZN", "SHEL", "NVS", "HSBC", "UL", "DEO", "BTI"],
    "EWJ": ["TM", "SONY", "MUFG", "HMC", "SMFG", "NMR", "MFG", "IX", "KB", "CAJ"],
    "EEM": ["TSM", "BABA", "PDD", "INFY", "IBN", "HDB", "VALE", "NU", "BIDU", "JD"],
    "EWY": ["005930.KS", "000660.KS", "373220.KS", "207940.KS", "005380.KS", "035420.KS", "000270.KS", "068270.KS"],
    "FXI": ["BABA", "PDD", "JD", "BIDU", "NTES", "YUMC", "TCOM", "LI", "BEKE", "ZTO"],
    "INDA": ["INFY", "IBN", "HDB", "WIT", "RDY", "SIFY", "TTM", "MMYT", "YTRA", "WNS"],
    "EWT": ["TSM", "UMC", "ASX", "CHT", "IMOS", "HIMX", "AUOTY", "LPL", "SIMO", "ACLS"],
    "GLD": ["NEM", "GOLD", "AEM", "FNV", "WPM", "KGC", "AU", "AGI", "HMY", "GFI"],
    "SLV": ["PAAS", "HL", "AG", "WPM", "CDE", "EXK", "FSM", "MAG", "SVM", "GATO"],
    "USO": ["XOM", "CVX", "COP", "OXY", "EOG", "DVN", "FANG", "APA", "MRO", "HES"],
    "DBC": ["XOM", "CVX", "NEM", "FCX", "ADM", "BG", "CTVA", "NUE", "SCCO", "MOS"],
    "BTC-USD": ["COIN", "MSTR", "MARA", "RIOT", "CLSK", "HUT", "CIFR", "IREN", "BTBT", "WULF"],
}
NO_STOCK_LEADERS = {"TLT", "IEF", "LQD", "HYG", "UUP"}


def theme_for_etf(ticker: str) -> Optional[str]:
    """섹터·테마 ETF 티커가 core.sector_strength.THEME_UNIVERSE 의 어느 테마 프록시인지(없으면 None)."""
    from core.sector_strength import THEME_UNIVERSE  # noqa: PLC0415

    for theme, proxies in THEME_UNIVERSE.items():
        if ticker in proxies:
            return theme
    return None


def leader_candidates(ticker: str) -> tuple[list[str], str]:
    """(후보 종목 리스트, 출처 설명). 후보가 없으면 빈 리스트와 이유를 돌려준다."""
    if ticker in NO_STOCK_LEADERS:
        return [], "채권·달러 시장은 개별 종목 주도주가 없습니다."
    theme = theme_for_etf(ticker)
    if theme:
        from core.sector_leaders import get_theme_candidate_tickers  # noqa: PLC0415

        return get_theme_candidate_tickers(theme), f"테마 '{theme}' 후보(S&P500 구성종목 또는 니치 프리셋)"
    if ticker in LEADER_PRESETS:
        return LEADER_PRESETS[ticker], "시장 대표 후보 프리셋(코드에 고정된 목록)"
    return [], "이 시장은 후보 목록이 없습니다."
