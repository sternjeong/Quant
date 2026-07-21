"""(부가) 코스톨라니 달걀 이론(Kostolany's Egg Theory) 기반 시장/섹터 국면 판정.

앙드레 코스톨라니의 달걀 이론은 시장 참여자의 "심리"(투자자 수·거래량 증감)를 축으로 시장을
A1(저점 조정) → A2(상승) → A3(버블/과열) → B1(고점 조정 시작) → B2(하락) → B3(패닉/급락) → 다시
A1의 6국면 순환으로 설명한다(투자자는 A1~B3, 즉 "거래량이 낮고 조정 중"일 때 사고 A3~B1, 즉
"거래량이 높고 과열/고점"일 때 팔라는 것이 이론의 핵심 조언).

이 앱은 "투자자 수" 같은 심리 데이터가 없으므로, 가격·거래량만으로 근사한다(2026-07-21, 사용자
확인 하에 채택):
  1. 위치(zone) — 52주 고점/저점 대비 현재가의 백분위 위치. 저점권(≤30)/중간/고점권(≥70).
  2. 추세(trend) — ROC(20거래일) 부호(상승/하락) + 급락 여부(패닉 판정용, 큰 폭의 하락).
  3. 거래량(volume) — 최근 20일 평균 거래량 / 60일 평균 거래량 비율이 1.2 이상이면 "증가".

공식 경기판단이 아닌 참고용 경험칙이며, core.market_regime/core.sector_strength와 마찬가지로
UI에 그 사실을 명시한다.
"""

from __future__ import annotations

import io
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from core.backtest_engine import DEFAULT_BENCHMARK_TICKER
from core.db import get_session
from core.indicators import roc
from core.market_data import get_multiple_price_history, get_price_history
from core.models import KostolanyCycleSnapshot
from core.sector_strength import THEME_UNIVERSE

# scripts/nightly_market_snapshot_ci.py가 매일 밤 커밋해두는 폴백 스냅샷 (core.market_regime의
# 동일 패턴, 2026-07-21 — Oracle VM 확보 전 임시 조치).
_CI_SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "kostolany_cycle_snapshot_ci.json"

DEFAULT_LOOKBACK_DAYS = 800  # 52주(252거래일) 위치 계산 + 거래량 60일 평균 대비 넉넉한 여유

POSITION_LOOKBACK_TRADING_DAYS = 252
ZONE_LOW_PCT = 30.0  # 이하면 "저점권"
ZONE_HIGH_PCT = 70.0  # 이상이면 "고점권"

TREND_ROC_WINDOW = 20
STEEP_ROC_PCT = 15.0  # |ROC(20)| 이상이면 "급등/급락"으로 간주(패닉/버블 판정 보조)

VOLUME_SHORT_WINDOW = 20
VOLUME_LONG_WINDOW = 60
VOLUME_HIGH_RATIO = 1.2  # 20일 평균 / 60일 평균이 이 이상이면 "거래량 증가"

PHASE_ORDER = ["A1", "A2", "A3", "B1", "B2", "B3"]

# 국면을 실행 가능한 3단계 상태("매수 관심"/"보유·관망"/"매도 검토")로 묶는다 — UI가 6개 국면을
# 개별로 나열하는 대신 코스톨라니의 핵심 조언(저거래량 조정 국면에서 사고, 고거래량 과열 국면에서
# 팔라) 기준으로 바로 실행 가능한 그룹을 먼저 보여줄 수 있게 한다.
PHASE_STATUS = {
    "A1": "buy", "B3": "buy",
    "A2": "hold", "B2": "hold",
    "A3": "sell", "B1": "sell",
}

STATUS_ORDER = ["buy", "hold", "sell"]
STATUS_LABELS = {"buy": "🟢 매수 관심", "hold": "⚪ 보유 · 관망", "sell": "🔴 매도 검토"}

# 장기 투자자와 스윙 트레이더는 같은 국면을 서로 다르게 해석한다(2026-07-21, 사용자 요청 —
# "내 니드에 맞게 스윙/장기 전략에 맞게 띄워주는 슬롯"). 장기(PHASE_STATUS)는 코스톨라니 원전의
# 조언 그대로(저거래량 조정·패닉에서 매집, 고거래량 과열·고점이탈에서 비중축소)를 따르지만, 스윙은
# "확인된 모멘텀을 단기로 타는" 관점이라 완전히 다르게 갈린다:
#   - A1(저점권, 아직 하락 진정 단계): 장기="매수"(미리 매집) vs 스윙="관망"(반등 확인 전 진입은
#     이르다고 봄)
#   - A2(거래량 동반 상승): 장기="보유" vs 스윙="매수"(스윙은 확인된 상승 추세를 그때 타야 함)
#   - B3(패닉 급락 진행 중): 장기="매수"(저점 매집) vs 스윙="매수"(단, 역추세 반등 노림수라 고위험 —
#     둘 다 buy지만 근거가 다르므로 STYLE_PHASE_GUIDANCE에서 문구로 구분)
# A3/B1(과열/고점이탈)은 두 스타일 모두 "매도"로 일치 — 어느 쪽이든 고점권+거래량 신호는 리스크
# 신호이기 때문.
SWING_PHASE_STATUS = {
    "A1": "hold", "B3": "buy",
    "A2": "buy", "B2": "hold",
    "A3": "sell", "B1": "sell",
}

STYLE_ORDER = ["장기", "스윙"]
STYLE_LABELS = {"장기": "🐢 장기 투자", "스윙": "⚡ 스윙 트레이딩"}
STYLE_PHASE_STATUS = {"장기": PHASE_STATUS, "스윙": SWING_PHASE_STATUS}

PHASE_INFO: dict[str, dict[str, str]] = {
    "A1": {
        "label": "A1 · 저점 조정",
        "description": "저점권에서 하락세가 진정되거나 반등 초입인 국면. 거래량은 아직 늘지 않았다.",
        "guidance": "매수 관심 구간(코스톨라니가 '사라'고 한 저거래량 조정 국면).",
    },
    "A2": {
        "label": "A2 · 상승",
        "description": "가격이 중간~상단 구간에서 상승하며 거래량도 함께 늘어나는 국면.",
        "guidance": "보유/추세 추종 구간.",
    },
    "A3": {
        "label": "A3 · 버블/과열",
        "description": "고점권에서 거래량이 급증하며 오르는 국면(과열·투기적 참여 확대).",
        "guidance": "매도 검토 구간(코스톨라니가 '팔라'고 한 고거래량 과열 국면).",
    },
    "B1": {
        "label": "B1 · 고점 조정 시작",
        "description": "고점권에서 막 하락으로 전환됐지만 아직 거래량은 낮은 국면.",
        "guidance": "매도 검토 구간(고점권 이탈 초입).",
    },
    "B2": {
        "label": "B2 · 하락",
        "description": "가격이 중간~하단 구간에서 하락하며 거래량도 늘어나는 국면.",
        "guidance": "관망 구간.",
    },
    "B3": {
        "label": "B3 · 패닉/급락",
        "description": "저점권에서 거래량 급증을 동반한 급락(패닉 투매) 국면.",
        "guidance": "매수 관심 구간(코스톨라니가 '사라'고 한 저점 패닉 국면) — 단, 급락 진행 중이라 변동성 매우 높음.",
    },
}

# 스타일별 실행 가이드 문구. "장기"는 PHASE_INFO의 기존 guidance를 그대로 재사용하고, "스윙"만
# SWING_PHASE_STATUS 관점에 맞는 별도 문구를 둔다(위 SWING_PHASE_STATUS 주석 참고).
STYLE_PHASE_GUIDANCE: dict[str, dict[str, str]] = {
    "장기": {phase: info["guidance"] for phase, info in PHASE_INFO.items()},
    "스윙": {
        "A1": "관망 — 저점권이지만 아직 반등이 확인되지 않아 스윙 진입은 이르다.",
        "A2": "추세추종 매수 — 거래량을 동반한 확인된 상승, 스윙 진입 후보.",
        "A3": "익절 / 신규진입 자제 — 과열 구간, 보유 중이면 트레일링 스탑으로 대응.",
        "B1": "매도 / 공매도 검토 — 고점 이탈 초입, 단기 하락에 베팅할 수 있는 구간.",
        "B2": "관망 — 하락이 진행 중, 거래량 급증 등 바닥 신호가 나올 때까지 대기.",
        "B3": "역추세 매수 후보(고위험) — 패닉 저점 반등을 노리는 단기 진입, 손절 기준 필수.",
    },
}


def _default_start() -> str:
    return (date.today() - timedelta(days=DEFAULT_LOOKBACK_DAYS)).isoformat()


def compute_position_pct(close: pd.Series, lookback: int = POSITION_LOOKBACK_TRADING_DAYS) -> Optional[float]:
    """52주(거래일 기준) 고점/저점 대비 현재가의 상대 위치를 0~100 백분위로 계산한다."""
    s = close.dropna()
    if s.empty:
        return None
    window = s.iloc[-lookback:] if len(s) > lookback else s
    lo, hi = float(window.min()), float(window.max())
    if hi == lo:
        return 50.0
    return (float(s.iloc[-1]) - lo) / (hi - lo) * 100


def compute_volume_ratio(
    volume: pd.Series, short: int = VOLUME_SHORT_WINDOW, long: int = VOLUME_LONG_WINDOW
) -> Optional[float]:
    """최근 20일 평균 거래량 / 60일 평균 거래량 비율을 계산한다(거래량 증감 추세용)."""
    s = volume.dropna()
    if len(s) < long:
        return None
    avg_long = float(s.iloc[-long:].mean())
    if avg_long == 0:
        return None
    avg_short = float(s.iloc[-short:].mean())
    return avg_short / avg_long


def _zone(position_pct: float) -> str:
    if position_pct <= ZONE_LOW_PCT:
        return "저점권"
    if position_pct >= ZONE_HIGH_PCT:
        return "고점권"
    return "중간"


def classify_cycle_phase(close: pd.Series, volume: pd.Series) -> Optional[dict]:
    """종가/거래량 시계열로 코스톨라니 달걀 6국면(A1~B3) 중 하나를 판정한다.

    판정 로직(모듈 docstring의 3축 조합):
    - 저점권(zone) + 하락(trend down): 급락(|ROC|≥15%)이고 거래량 증가면 B3(패닉), 아니면 A1(저점조정)
    - 저점권 + 상승: 거래량 증가면 A2(초기 상승 전환), 아니면 A1(반등 초입, 아직 저거래량)
    - 고점권 + 상승: 거래량 증가면 A3(버블/과열), 아니면 A2(연장 상승)
    - 고점권 + 하락: 거래량 증가면 B2(본격 하락), 아니면 B1(고점 조정 시작)
    - 중간: 상승이면 A2, 하락이면 B2

    Returns:
        {"phase": str, "position_pct": float, "roc_pct": float, "volume_ratio": float|None,
         "zone": str, "trend_up": bool, "is_steep": bool, "volume_high": bool, **PHASE_INFO[phase]}
        데이터가 부족하면 None.
    """
    position_pct = compute_position_pct(close)
    if position_pct is None:
        return None
    roc_series = roc(close.dropna(), TREND_ROC_WINDOW)
    if roc_series.dropna().empty:
        return None
    roc_pct = float(roc_series.iloc[-1])

    zone = _zone(position_pct)
    trend_up = roc_pct > 0
    is_steep = abs(roc_pct) >= STEEP_ROC_PCT
    volume_ratio = compute_volume_ratio(volume)
    volume_high = volume_ratio is not None and volume_ratio >= VOLUME_HIGH_RATIO

    if zone == "저점권":
        if trend_up:
            phase = "A2" if volume_high else "A1"
        else:
            phase = "B3" if (volume_high and is_steep) else "A1"
    elif zone == "고점권":
        if trend_up:
            phase = "A3" if volume_high else "A2"
        else:
            phase = "B2" if volume_high else "B1"
    else:
        phase = "A2" if trend_up else "B2"

    result = {
        "phase": phase,
        "position_pct": position_pct,
        "roc_pct": roc_pct,
        "volume_ratio": volume_ratio,
        "zone": zone,
        "trend_up": trend_up,
        "is_steep": is_steep,
        "volume_high": volume_high,
    }
    result.update(PHASE_INFO[phase])
    return result


def explain_phase_reasoning(row: dict, style: str = "장기") -> str:
    """classify_cycle_phase()(또는 compute_theme_cycle_phases()의 한 행)가 왜 그 국면(A1~B3)을
    골랐는지 3축(위치/추세/거래량) 판정 근거와 최종 분기 로직을 사람이 읽을 수 있는 리포트로 풀어쓴다
    (2026-07-21, 사용자가 "섹터를 클릭하면 왜 그렇게 판단했는지 리포트를 보고 싶다"고 요청).

    row는 최소한 phase/zone/position_pct/roc_pct/volume_ratio/trend_up/is_steep/volume_high 키를
    가진 dict(또는 pandas.Series로 그 키들에 접근 가능한 값) — classify_cycle_phase()의 반환값이나
    compute_theme_cycle_phases()가 만드는 DataFrame의 각 행이 그대로 맞는다.
    """
    phase = row["phase"]
    zone = row["zone"]
    position_pct = row["position_pct"]
    roc_pct = row["roc_pct"]
    volume_ratio = row.get("volume_ratio")
    trend_up = row["trend_up"]
    is_steep = row.get("is_steep", False)
    volume_high = row.get("volume_high", False)

    zone_line = (
        f"**① 위치(52주 고점·저점 대비)**: 현재가가 52주 구간의 {position_pct:.0f}% 지점입니다 "
        f"(0%=52주 최저가, 100%=52주 최고가). {ZONE_LOW_PCT:.0f}% 이하는 저점권, {ZONE_HIGH_PCT:.0f}% "
        f"이상은 고점권으로 판정하는 기준이라 → **{zone}**."
    )

    steep_note = (
        f" 이 중 절댓값이 {STEEP_ROC_PCT:.0f}% 이상이라 '급등/급락'으로도 함께 판정됩니다(패닉 국면 B3 "
        "판정에 쓰이는 조건)."
        if is_steep
        else f" 급락/급등 기준(±{STEEP_ROC_PCT:.0f}%)에는 못 미치는 완만한 변화입니다."
    )
    trend_line = (
        f"**② 추세(최근 {TREND_ROC_WINDOW}거래일 등락률)**: {roc_pct:+.1f}%로 "
        f"{'상승' if trend_up else '하락'} 추세입니다.{steep_note}"
    )

    if volume_ratio is None:
        volume_line = "**③ 거래량**: 60일 평균 거래량을 계산할 이력이 부족해 판정에서 제외됐습니다(거래량 증가 아님으로 처리)."
    else:
        volume_line = (
            f"**③ 거래량(최근 {VOLUME_SHORT_WINDOW}일 평균 ÷ {VOLUME_LONG_WINDOW}일 평균)**: {volume_ratio:.2f}배로, "
            f"{VOLUME_HIGH_RATIO:.1f}배 이상이면 '거래량 증가'로 봅니다 → "
            f"{'거래량 증가' if volume_high else '평범한 수준(증가 아님)'}."
        )

    if zone == "저점권":
        if trend_up:
            branch = (
                "저점권 + 상승 추세이므로, 거래량이 증가했으면 A2(초기 상승 전환), 아니면 A1(저점 조정, "
                "아직 저거래량 반등 초입)로 판정합니다."
            )
        else:
            branch = (
                "저점권 + 하락 추세이므로, '급락 + 거래량 증가'가 동시에 맞으면 B3(패닉/급락 투매)로, "
                "아니면 A1(저점 조정)로 판정합니다."
            )
    elif zone == "고점권":
        if trend_up:
            branch = (
                "고점권 + 상승 추세이므로, 거래량이 증가했으면 A3(버블/과열), 아니면 A2(상승 연장)로 "
                "판정합니다."
            )
        else:
            branch = (
                "고점권 + 하락 추세이므로, 거래량이 증가했으면 B2(본격 하락), 아니면 B1(고점 조정 시작)로 "
                "판정합니다."
            )
    else:
        branch = "중간 구간이라 위치만으로는 애매해, 추세 방향만으로 상승이면 A2, 하락이면 B2로 판정합니다."
    branch_line = f"**④ 종합 판정**: {branch} → 결과 **{PHASE_INFO[phase]['label']}**."

    guidance = STYLE_PHASE_GUIDANCE.get(style, STYLE_PHASE_GUIDANCE["장기"])[phase]
    guidance_line = f"**⑤ {STYLE_LABELS.get(style, style)} 관점 실행 가이드**: {guidance}"

    return "\n\n".join([zone_line, trend_line, volume_line, branch_line, guidance_line])


def get_market_cycle_phase(benchmark_ticker: str = DEFAULT_BENCHMARK_TICKER) -> Optional[dict]:
    """전체 시장(기본 S&P500 지수)의 코스톨라니 달걀 국면을 계산한다."""
    df = get_price_history(benchmark_ticker, start=_default_start(), end=None, interval="1d")
    if df is None or df.empty or "Close" not in df.columns or "Volume" not in df.columns:
        return None
    result = classify_cycle_phase(df["Close"], df["Volume"])
    if result is not None:
        result["ticker"] = benchmark_ticker
    return result


def _combined_close_volume(proxies: list[str], start: Optional[str] = None, end: Optional[str] = None):
    """프록시 여러 개면 정규화된(첫날=100) 종가 평균 + 거래량 합산으로 테마 대표 시계열을 만든다.

    core.sector_strength.theme_price_history()와 같은 종가 정규화 방식을 쓰되, 거래량(20일/60일
    평균 비율만 필요하므로 절대 스케일은 무관 — 합산)까지 함께 반환한다.
    """
    histories = get_multiple_price_history(proxies, start=start or _default_start(), end=end, interval="1d")
    closes, volumes = [], []
    for df in histories.values():
        if df is None or df.empty or "Close" not in df.columns:
            continue
        close = df["Close"].dropna()
        if close.empty:
            continue
        closes.append(close / float(close.iloc[0]) * 100)
        if "Volume" in df.columns:
            volumes.append(df["Volume"].dropna())
    if not closes:
        return None, None
    combined_close = pd.concat(closes, axis=1).mean(axis=1).dropna()
    combined_volume = pd.concat(volumes, axis=1).sum(axis=1).dropna() if volumes else pd.Series(dtype=float)
    return (combined_close if not combined_close.empty else None), combined_volume


def compute_theme_cycle_phases(
    theme_universe: Optional[dict[str, list[str]]] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DataFrame:
    """core.sector_strength.THEME_UNIVERSE의 모든 테마에 대해 코스톨라니 달걀 국면을 계산한다.

    Returns:
        columns: theme, proxies, phase, label, zone, position_pct, roc_pct, volume_ratio,
        trend_up, is_steep, volume_high, description, guidance
    """
    themes = THEME_UNIVERSE if theme_universe is None else theme_universe
    rows = []
    for theme, proxies in themes.items():
        close, volume = _combined_close_volume(proxies, start, end)
        if close is None or volume is None or volume.empty:
            continue
        result = classify_cycle_phase(close, volume)
        if result is None:
            continue
        rows.append({"theme": theme, "proxies": ", ".join(proxies), **result})

    columns = [
        "theme", "proxies", "phase", "label", "zone", "position_pct", "roc_pct",
        "volume_ratio", "trend_up", "is_steep", "volume_high", "description", "guidance",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    df = pd.DataFrame(rows)[columns]
    df["phase_order"] = df["phase"].map({p: i for i, p in enumerate(PHASE_ORDER)})
    df = df.sort_values("phase_order").drop(columns="phase_order").reset_index(drop=True)
    return df


def save_kostolany_cycle_snapshot(market_phase: Optional[dict], theme_phases: pd.DataFrame) -> int:
    """계산 결과를 DB에 저장한다 (core.market_regime/core.sector_strength와 동일한 스냅샷 패턴)."""
    with get_session() as session:
        row = KostolanyCycleSnapshot(
            market_phase=market_phase["phase"] if market_phase else None,
            market_detail=json.dumps(market_phase, ensure_ascii=False) if market_phase else None,
            theme_phases=theme_phases.to_json(orient="records", force_ascii=False),
        )
        session.add(row)
        session.flush()
        return row.id


def _load_ci_snapshot() -> Optional[dict]:
    """scripts/nightly_market_snapshot_ci.py가 커밋해둔 폴백 스냅샷을 읽는다. 없거나 깨졌으면 None."""
    if not _CI_SNAPSHOT_PATH.exists():
        return None
    try:
        raw = json.loads(_CI_SNAPSHOT_PATH.read_text(encoding="utf-8"))
        df = pd.DataFrame(raw["theme_phases"])
        return {
            "market_phase": raw.get("market_phase"),
            "theme_phases": df,
            "computed_at": datetime.fromisoformat(raw["computed_at"]),
        }
    except (json.JSONDecodeError, OSError, KeyError, ValueError):
        return None


def get_latest_kostolany_cycle_snapshot() -> Optional[dict]:
    """가장 최근에 저장된 코스톨라니 달걀 국면 스냅샷을 반환한다. 아직 하나도 없으면 None.

    로컬 DB와 GitHub Actions 폴백 JSON 중 더 최신인 쪽을 반환한다(core.market_regime.
    get_latest_market_regime_snapshot과 동일한 이유/패턴, 2026-07-21).

    Returns: {"market_phase": dict|None, "theme_phases": DataFrame, "computed_at": datetime} 또는 None.
    """
    with get_session() as session:
        row = (
            session.query(KostolanyCycleSnapshot)
            .order_by(KostolanyCycleSnapshot.id.desc())
            .first()
        )
        db_result = None
        if row is not None:
            market_detail = json.loads(row.market_detail) if row.market_detail else None
            df = pd.read_json(io.StringIO(row.theme_phases), orient="records")
            db_result = {"market_phase": market_detail, "theme_phases": df, "computed_at": row.computed_at}

    ci_result = _load_ci_snapshot()

    if db_result is None:
        return ci_result
    if ci_result is None:
        return db_result
    return ci_result if ci_result["computed_at"] > db_result["computed_at"] else db_result
