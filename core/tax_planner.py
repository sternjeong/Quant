"""내 계좌 세금 플래너 (2026-10-05, 사용자 요청 "세금들도 고려하도록 엔진을 구축해주라").

core/tax_fx.py 가 '과거에 이 전략을 굴렸다면'을 계산한다면, 이 모듈은 '지금 내 계좌'를 본다:
  - 포트폴리오 화면에 입력한 보유(매입일·단가·수량)와 매입일 환율로 원화 취득가를 만들고, 지금 가격·환율로 미실현 손익(원)을 낸다.
  - '지금 할 일' 주문 목록의 매도마다 실현될 차익(원)과, 올해 이미 실현한 이익(사용자가 입력 — 증권사 앱의 양도세 예상 화면 값)을
    더해 250만 원 공제 잔액과 내년 5월에 낼 세금(22%)을 추정한다.
  - 연말 제안: 공제가 남으면 '공제 채우기'(이익 난 종목을 일부 팔았다 바로 다시 사서 취득가를 올림), 공제를 넘으면
    '손실 확정'(손실 난 종목을 팔았다 바로 다시 사서 상계). 둘 다 보유는 그대로다. 한국 해외주식 양도세에는 미국식
    '팔고 바로 다시 사기 금지(wash sale)' 규정이 없다고 알려져 있으나 확인 필요로 표시한다.
매매 규칙(언제 무엇을 사고파나)은 바꾸지 않는다 — 세금을 줄이는 규칙 변형은 연구 작업 tax-rnd-v1 이 판정한다.
2026-11-20 엔진 반영(사용자 승인): frontier-tax-allowance-v2 에서 유일하게 통과한 '원가 올리기'(H0_MKT_STEPUP, ALLOWANCE_HELPS)의
고정 규칙을 따른다 — 12월에만, 평가이익률 2% 이상인 종목만(왕복 0.3% ÷ 22% ≈ 1.36% 손익분기 + 여유). 12/1~12/26 아침
텔레그램에 내 보유로 계산한 종목·수량이 나온다. 올해 실현 이익을 입력하지 않았으면 수량을 내지 않는다(이미 공제를 썼으면 세금이 생김).
추정치이며 신고용이 아니다. 주문 경로와 연결되어 있지 않다.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from core.tax_fx import ANNUAL_DEDUCTION_KRW, KAKAO_FEE, TAX_RATE

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = PROJECT_ROOT / "data" / "tax_year.json"
HARVEST_FROM = (12, 1)  # 이 날(월, 일)부터 연말 제안을 '지금 할 때'로 표시(frontier-tax-allowance-v2: 12월에만)
REMINDER_FROM = (11, 15)  # 이 날부터 아침 텔레그램에 연말 점검 줄
REMINDER_UNTIL = (12, 26)
STEPUP_MIN_GAIN_RATIO = 0.02  # frontier-tax-allowance-v2 고정 규칙: 평가이익률 2% 이상일 때만 원가 올리기
SETTLEMENT_NOTE = ("미국 주식은 결제일 기준으로 해가 정해집니다 — 12월 마지막 거래일 2~3일 전까지 하세요"
                   "(정확한 마감일은 카카오페이증권 연말 공지 확인).")
WASH_SALE_NOTE = "팔고 바로 다시 사는 것을 막는 규정(미국식 wash sale)은 한국 해외주식 양도세에 없다고 알려져 있습니다(확인 필요)."


# ---------------------------------------------------------------- 올해 실현 이익(사용자 입력)
def load_realized(year: int, path: Optional[Path] = None) -> Optional[float]:
    p = Path(path or STATE_PATH)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        v = (data.get("years") or {}).get(str(year), {}).get("realized_krw")
        return None if v is None else float(v)
    except (OSError, ValueError, AttributeError):
        return None


def save_realized(year: int, krw: float, path: Optional[Path] = None) -> None:
    p = Path(path or STATE_PATH)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("years", {})[str(year)] = {
        "realized_krw": float(krw), "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tax_year.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


# ---------------------------------------------------------------- 보유 → 원화 손익
def fx_on(fx: pd.Series, d: Any) -> float:
    """d 날짜(또는 그 전 마지막) 환율. d 가 시계열보다 앞이면 첫 값."""
    s = fx.dropna().sort_index()
    ts = pd.Timestamp(d)
    before = s[s.index <= ts]
    return float(before.iloc[-1] if not before.empty else s.iloc[0])


def positions(holdings: list[dict], prices: dict[str, Optional[float]], fx: pd.Series,
              fee_rate: float = KAKAO_FEE) -> list[dict]:
    """종목별: 수량, 원화 취득가(매입일 환율, 매수 수수료 포함 근사 — 이동평균), 지금 팔면 받을 원화(수수료 뺌), 미실현 손익.
    가격이 없는 종목은 price=None 으로 손익을 비운다."""
    fx_now = float(fx.dropna().iloc[-1])
    by: dict[str, dict] = {}
    for h in holdings:
        q = float(h.get("quantity") or 0.0)
        if q <= 0:
            continue
        cost = q * float(h.get("purchase_price") or 0.0) * (1 + fee_rate) * fx_on(fx, h.get("purchase_date"))
        p = by.setdefault(h["ticker"], {"ticker": h["ticker"], "shares": 0.0, "cost_krw": 0.0,
                                        "first_date": h.get("purchase_date")})
        p["shares"] += q
        p["cost_krw"] += cost
    out = []
    for t, p in sorted(by.items()):
        px = prices.get(t)
        p["price"] = px
        p["fx_now"] = fx_now
        if px and px > 0:
            p["value_krw"] = p["shares"] * px * (1 - fee_rate) * fx_now
            p["gain_krw"] = p["value_krw"] - p["cost_krw"]
            p["gain_per_share_krw"] = p["gain_krw"] / p["shares"]
        else:
            p["value_krw"] = p["gain_krw"] = p["gain_per_share_krw"] = None
        out.append(p)
    return out


def sell_estimates(order_rows: list[dict], pos: list[dict]) -> list[dict]:
    """주문 목록(order_rows_with_shares 결과)의 매도마다 실현될 차익(원, 이동평균 근사)."""
    by = {p["ticker"]: p for p in pos}
    out = []
    for r in order_rows:
        if r.get("action") not in ("매도", "전량 매도"):
            continue
        p = by.get(r["ticker"])
        q = r.get("whole_shares", r.get("shares"))  # 2026-10-08 주문 목록은 정수 주 주문
        if r.get("action") == "전량 매도" and p:
            q = p["shares"]
        gain = None
        if p and p.get("gain_per_share_krw") is not None and q:
            gain = float(q) * p["gain_per_share_krw"]
        out.append({"ticker": r["ticker"], "action": r["action"], "shares": q, "gain_krw": gain,
                    "known": gain is not None})
    return out


def year_summary(realized_ytd: Optional[float], planned_gain: float, year: int) -> dict:
    """올해 실현(입력값) + 이번 매도 → 공제 잔액·예상 세금(다음 해 5월 납부)."""
    base = float(realized_ytd or 0.0)
    total = base + float(planned_gain)
    return {
        "year": year, "realized_ytd_krw": realized_ytd, "planned_krw": float(planned_gain), "total_krw": total,
        "deduction_left_krw": max(0.0, ANNUAL_DEDUCTION_KRW - total),
        "tax_krw": max(0.0, total - ANNUAL_DEDUCTION_KRW) * TAX_RATE,
        "tax_without_plan_krw": max(0.0, base - ANNUAL_DEDUCTION_KRW) * TAX_RATE,
        "due": f"{year + 1}-05-31",
    }


def harvest_suggestions(pos: list[dict], realized_total: float, today: date,
                        fee_rate: float = KAKAO_FEE) -> dict:
    """연말 공제 채우기·손실 확정 제안. 매매 규칙은 바꾸지 않는다(팔았다 같은 날 같은 수량을 다시 산다)."""
    actionable = (today.month, today.day) >= HARVEST_FROM
    rows: list[dict] = []
    kind = None
    if realized_total < ANNUAL_DEDUCTION_KRW:
        kind = "gain"
        room = (ANNUAL_DEDUCTION_KRW - realized_total) * 0.97
        for p in sorted((p for p in pos if (p.get("gain_per_share_krw") or 0) > 0
                         and p["gain_krw"] >= STEPUP_MIN_GAIN_RATIO * p["cost_krw"]),
                        key=lambda p: -p["gain_per_share_krw"]):
            if room <= 0:
                break
            q = min(p["shares"], room / p["gain_per_share_krw"])
            if p["shares"] >= 1:
                q = float(int(q)) if q >= 1 else q  # 정수 주가 가능하면 정수로(소수점 매매가 되면 그대로 써도 됨)
            if q <= 0:
                continue
            g = q * p["gain_per_share_krw"]
            cost = 2 * q * p["price"] * fee_rate * p["fx_now"]
            rows.append({"ticker": p["ticker"], "shares": q, "realize_krw": g, "fees_krw": cost,
                         "tax_saved_later_krw": g * TAX_RATE})
            room -= g
    elif realized_total > ANNUAL_DEDUCTION_KRW:
        kind = "loss"
        need = realized_total - ANNUAL_DEDUCTION_KRW
        for p in sorted((p for p in pos if (p.get("gain_per_share_krw") or 0) < 0),
                        key=lambda p: p["gain_per_share_krw"]):
            if need <= 0:
                break
            q = min(p["shares"], need / -p["gain_per_share_krw"])
            if p["shares"] >= 1 and q >= 1:
                q = float(int(q)) or q
            g = q * p["gain_per_share_krw"]
            cost = 2 * q * p["price"] * fee_rate * p["fx_now"]
            rows.append({"ticker": p["ticker"], "shares": q, "realize_krw": g, "fees_krw": cost,
                         "tax_saved_now_krw": -g * TAX_RATE})
            need += g
    total_saved = sum(r.get("tax_saved_later_krw", r.get("tax_saved_now_krw", 0.0)) for r in rows)
    total_fees = sum(r["fees_krw"] for r in rows)
    return {"kind": kind, "actionable": actionable, "rows": rows, "tax_saved_krw": total_saved, "fees_krw": total_fees,
            "worth_it": total_saved > total_fees * 2,
            "notes": [SETTLEMENT_NOTE, WASH_SALE_NOTE,
                      "공제 채우기는 세금을 없애는 게 아니라 취득가를 올려 나중 세금을 줄이는 것이고, 손실 확정은 올해 세금을 바로 줄입니다."]}


def year_end_reminder_line(today: date) -> Optional[str]:
    """아침 텔레그램용 한 줄 — 11/15~11/30 미리 알림, 12/1~12/26 실행 안내(내 보유 계산은 year_end_message)."""
    if (today.month, today.day) < REMINDER_FROM or (today.month, today.day) > REMINDER_UNTIL:
        return None
    if (today.month, today.day) < HARVEST_FROM:
        return ("🧾 연말 세금 준비: 12월 1일부터 아침 메시지에 원가 올리기(공제 250만 원) 종목·수량이 나옵니다 — "
                "그 전에 '세후 수익 계산' 화면 '내 계좌 올해 세금'에 올해 실현 이익을 넣어 두세요(없으면 0).")
    return ("🧾 연말 원가 올리기 시기(12월 마지막 거래일 2~3일 전까지): '세후 수익 계산' 화면 '내 계좌 올해 세금'에 "
            "올해 실현 이익을 넣으면 종목·수량이 나옵니다(없으면 0).")


def _fmt_shares(q: float) -> str:
    return f"{int(q)}주" if float(q).is_integer() else f"{q:.4f}주"


def year_end_lines(today: date, pos: list[dict], realized_ytd: Optional[float]) -> Optional[list[str]]:
    """12/1~12/26 아침 텔레그램용 연말 실행 안내(내 보유 기준). 기간 밖이면 None.
    올해 실현 이익이 입력되지 않았으면 수량을 내지 않는다 — 이미 공제를 썼다면 원가 올리기가 세금을 만든다."""
    if (today.month, today.day) < HARVEST_FROM or (today.month, today.day) > REMINDER_UNTIL:
        return None
    if realized_ytd is None:
        return [year_end_reminder_line(today) or ""]
    sug = harvest_suggestions(pos, float(realized_ytd), today)
    if not sug["rows"]:
        why = ("평가이익 2% 넘는 보유가 없거나 공제를 이미 다 씀" if sug["kind"] == "gain"
               else "손실 난 보유가 없음" if sug["kind"] == "loss" else "공제 250만 원을 정확히 씀")
        return [f"🧾 연말 세금: 지금 할 원가 올리기·손실 확정 없음({why})."]
    if sug["kind"] == "gain":
        head = (f"🧾 연말 원가 올리기: 아래만큼 팔고 같은 날 같은 수량을 다시 사세요(보유·비중 그대로). "
                f"나중 양도세 약 {sug['tax_saved_krw']:,.0f}원↓, 수수료 약 {sug['fees_krw']:,.0f}원")
    else:
        head = (f"🧾 연말 손실 확정: 아래만큼 팔고 같은 날 같은 수량을 다시 사세요(보유·비중 그대로). "
                f"올해 양도세 약 {sug['tax_saved_krw']:,.0f}원↓, 수수료 약 {sug['fees_krw']:,.0f}원")
    if not sug["worth_it"]:
        head += " — 수수료에 비해 이득이 작아 건너뛰어도 됩니다"
    lines = [head]
    lines += [f"  · {r['ticker']} {_fmt_shares(r['shares'])} (실현 {r['realize_krw']:,.0f}원)" for r in sug["rows"]]
    lines.append("  · 12월 마지막 거래일 2~3일 전까지(결제일 기준). 올해 실현 이익 입력값 "
                 f"{float(realized_ytd):,.0f}원 기준 추정이며 신고용이 아닙니다.")
    return lines


def year_end_message(today: date) -> Optional[str]:
    """아침 잡이 부른다: 기간 밖 None, 12월엔 내 보유·입력값으로 실행 안내, 계산이 안 되면 일반 안내 한 줄."""
    if (today.month, today.day) < HARVEST_FROM:
        return year_end_reminder_line(today)
    if (today.month, today.day) > REMINDER_UNTIL:
        return None
    try:
        from core import portfolio as pf
        from core.market_data import get_latest_price

        holdings = pf.list_holdings()
        if not holdings:
            return year_end_reminder_line(today)
        prices = {t: get_latest_price(t) for t in sorted({h["ticker"] for h in holdings})}
        lines = year_end_lines(today, positions(holdings, prices, load_fx()), load_realized(today.year))
        return "\n".join(lines) if lines else None
    except Exception:  # noqa: BLE001 - 계산이 안 되면 일반 안내로
        return year_end_reminder_line(today)


def load_fx() -> pd.Series:
    from core.tax_fx import usdkrw_series

    return usdkrw_series()
