"""모듈 B: Threads 글 → 티커별 요약 + 주간 AI 인사이트 리포트.

Threads 크롤링은 막혀 있으므로, 원문을 수동으로 붙여넣으면 AI가 관련 티커를 자동 인식하고
요약을 생성한다. GEMINI_API_KEY가 없거나 API 호출이 실패해도 예외를 던지지 않고
core.nl_strategy 와 동일한 패턴으로 키워드 기반 대체(fallback) 로직을 사용한다.

인식된 티커는 사용자가 직접 수정/재태깅할 수 있도록 저장 후에도 갱신 가능하게 한다.

generate_weekly_report()는 개별 글 요약과는 별개로, 최근 N일간 저장된 글 여러 개를 종합해
"단순 요약이 아닌" 테마/정서 변화/촉매·리스크/합의-소수의견/관찰포인트 인사이트 리포트를
생성한다 (사용자 버튼 클릭 또는 scheduler/run_scheduler.py의 주간 잡으로 트리거 가능).

generate_report_feedback()은 시간이 지난 뒤 그 리포트가 얼마나 맞았는지 사후 검증(회고)한다 —
리포트 생성 시점 가격과 현재 가격을 비교하고, 리포트에 적힌 테마/촉매/리스크/관찰포인트가 실제로
어떻게 됐는지 AI가 되짚어본다.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any, Optional

from core import gemini_client
from core.db import get_session
from core.market_data import get_latest_price
from core.models import ThreadsSummary, ThreadsWeeklyReport

# 자동 인식 fallback에서 오탐을 줄이기 위한 흔한 영어 단어 블랙리스트
# (모두 대문자 1~5자 토큰이라 티커 정규식과 겹칠 수 있음)
_COMMON_WORD_BLACKLIST = {
    "A", "I", "THE", "AND", "OR", "IF", "IS", "IT", "TO", "OF", "ON", "IN",
    "FOR", "BUY", "SELL", "ALL", "NEW", "CEO", "IPO", "ETF", "USD", "GDP",
    "EPS", "PER", "PBR", "ATH", "YOY", "QOQ", "FOMO", "YOLO", "DD", "IMO",
}

TICKER_RE = re.compile(r"\$?\b[A-Z]{1,5}\b")

SYSTEM_PROMPT = """\
당신은 투자 SNS(Threads) 글을 분석하는 애널리스트입니다.
사용자가 붙여넣은 글을 읽고:
1. 언급된 미국 주식 티커를 모두 찾아 대문자 배열로 반환하세요 (회사명만 언급된 경우 실제 티커로 변환).
2. 글의 핵심 내용을 3~5문장의 한국어로 요약하세요 (투자 관점에서 중요한 정보 위주).
"""

SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tickers": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["tickers", "summary"],
    "additionalProperties": False,
}


def _fallback_extract(raw_text: str) -> dict:
    """Claude API 없이 정규식으로 티커 후보를 추출하고, 원문 앞부분을 요약 대신 사용."""
    candidates = {m.group(0).lstrip("$") for m in TICKER_RE.finditer(raw_text)}
    tickers = sorted(t for t in candidates if t not in _COMMON_WORD_BLACKLIST)

    snippet = re.sub(r"\s+", " ", raw_text).strip()
    if len(snippet) > 200:
        snippet = snippet[:200] + "..."
    summary = (
        "[자동 요약 실패 - 원문 일부만 표시] "
        "GEMINI_API_KEY가 설정되지 않았거나 API 호출에 실패해 요약을 생성하지 못했습니다. "
        f"원문 앞부분: {snippet}"
    )
    return {"tickers": tickers, "summary": summary}


def analyze_text(raw_text: str) -> dict:
    """원문에서 티커를 인식하고 요약을 생성한다.

    Returns:
        {"tickers": list[str], "summary": str}

    GEMINI_API_KEY가 없거나 호출이 실패하면 _fallback_extract 로 대체한다 (예외를 던지지 않음).
    """
    if not gemini_client.has_api_key():
        return _fallback_extract(raw_text)

    try:
        response = gemini_client.generate_content(
            models=gemini_client.LIGHT_TASK_MODELS,
            contents=f"다음 글을 분석해줘:\n\n{raw_text}",
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema=SUMMARY_SCHEMA,
        )
        text = response.text
        if not text:
            return _fallback_extract(raw_text)
        parsed = json.loads(text)
        parsed["tickers"] = sorted({t.strip().upper() for t in parsed.get("tickers", []) if t.strip()})
        if not parsed.get("summary"):
            return _fallback_extract(raw_text)
        return parsed
    except Exception as e:
        fallback = _fallback_extract(raw_text)
        fallback["summary"] = f"[AI 호출 실패: {e}] " + fallback["summary"]
        return fallback


def save_summary(raw_text: str, tickers: list[str], ai_summary: str) -> int:
    """분석 결과를 저장한다 (사용자가 티커를 직접 수정한 최종본을 저장하는 용도).

    Returns:
        생성된 ThreadsSummary 의 id.
    """
    if not raw_text.strip():
        raise ValueError("원문이 비어 있습니다.")

    normalized_tickers = sorted({t.strip().upper() for t in tickers if t.strip()})
    with get_session() as session:
        row = ThreadsSummary(
            raw_text=raw_text,
            tickers=json.dumps(normalized_tickers),
            ai_summary=ai_summary,
        )
        session.add(row)
        session.flush()
        return row.id


def update_tickers(summary_id: int, tickers: list[str]) -> None:
    """저장된 요약의 티커 태깅을 수정한다 (자동 인식이 틀렸을 때 사용)."""
    normalized_tickers = sorted({t.strip().upper() for t in tickers if t.strip()})
    with get_session() as session:
        row = session.get(ThreadsSummary, summary_id)
        if row is None:
            raise ValueError(f"요약(id={summary_id})을 찾을 수 없습니다.")
        row.tickers = json.dumps(normalized_tickers)


def delete_summary(summary_id: int) -> None:
    with get_session() as session:
        row = session.get(ThreadsSummary, summary_id)
        if row is not None:
            session.delete(row)


def _row_to_dict(row: ThreadsSummary) -> dict:
    return {
        "id": row.id,
        "raw_text": row.raw_text,
        "tickers": json.loads(row.tickers) if row.tickers else [],
        "ai_summary": row.ai_summary or "",
        "created_at": row.created_at,
    }


def list_summaries(ticker: Optional[str] = None, limit: int = 200) -> list[dict]:
    """저장된 요약 목록을 최신순으로 반환한다. ticker를 지정하면 해당 티커가 태깅된 글만."""
    with get_session() as session:
        rows = session.query(ThreadsSummary).order_by(ThreadsSummary.created_at.desc()).limit(limit).all()
        result = [_row_to_dict(r) for r in rows]

    if ticker:
        ticker = ticker.strip().upper()
        result = [r for r in result if ticker in r["tickers"]]
    return result


def list_tracked_tickers() -> list[str]:
    """지금까지 인식/태깅된 티커 전체 목록(중복 제거, 알파벳순)을 반환한다 (티커별 필터 UI용)."""
    with get_session() as session:
        rows = session.query(ThreadsSummary.tickers).all()

    all_tickers: set[str] = set()
    for (tickers_json,) in rows:
        if tickers_json:
            all_tickers.update(json.loads(tickers_json))
    return sorted(all_tickers)


def get_ticker_history(ticker: str) -> list[dict]:
    """특정 티커에 대한 요약 히스토리를 시간순(오래된 것 먼저)으로 반환한다."""
    summaries = list_summaries(ticker=ticker)
    return list(reversed(summaries))


# ==============================================================================
# 주간 AI 인사이트 리포트: 개별 글 요약이 아니라, 최근 N일간 저장된 글 여러 개를
# 종합했을 때만 드러나는 테마/정서 변화/촉매·리스크를 뽑아내는 것이 목표.
# 사용자가 직접 버튼으로 즉시 생성하거나(app/pages/2_Threads_요약.py), 스케줄러가
# 매주 자동 생성(scheduler/run_scheduler.py::threads_weekly_report_job)할 수 있다.
# ==============================================================================

WEEKLY_REPORT_SYSTEM_PROMPT = """\
당신은 소셜 미디어(Threads)에 올라온 투자 관련 글들을 분석해 기관 애널리스트 수준의 주간 리포트를
작성하는 시니어 리서치 애널리스트입니다.

사용자가 특정 티커에 대해 최근 저장한 글 여러 개(원문 요약, 시간순)를 전달할 것입니다. 당신의
임무는 이 글들을 단순히 이어붙여 요약하는 것이 아니라, 여러 글을 종합해서 볼 때만 드러나는 흐름과
통찰을 뽑아내는 것입니다. 개별 글 하나하나의 재탕이 아니라 "여러 글을 겹쳐 봤을 때 보이는 것"에
집중하세요.

다음 구조로 한국어 리포트를 작성하세요 (마크다운 소제목으로 섹션을 구분):

1. **이번 주 핵심 테마 (Key Themes)**: 여러 글을 관통하는 공통된 화제/서사를 2~4개로 압축하고,
   왜 이 테마가 반복되는지도 짚어주세요.
2. **정서 변화 (Sentiment Shift)**: 기간 초반과 후반의 분위기(낙관/비관/중립)를 비교하고, 방향이
   바뀌었다면 그 변곡점이 된 글/사건을 구체적으로 짚어주세요. 글이 시간순으로 주어지니 흐름을
   추적하세요.
3. **촉매 및 리스크 (Catalysts & Risks)**: 글에서 언급된 다가올 이벤트(실적 발표, 제품 출시, 규제
   등)와 잠재 리스크 요인을 구분해서 나열하세요.
4. **다수 의견 vs 소수 의견 (Consensus vs Outlier)**: 여러 글이 동의하는 지배적 견해와, 그와
   반대되거나 소수인 의견을 구분해주세요 (에코챔버 여부를 파악하는 데 중요합니다).
5. **관찰 포인트 (What to Watch)**: 위 분석을 종합했을 때 다음 기간에 특히 주목해야 할 지점을
   2~3개로 제시하세요.

글이 1~2개뿐이라 "여러 글을 종합"하기 어려우면 그 사실을 리포트 서두에 명시하고, 있는 정보 안에서
최선의 분석을 제공하세요. 투자 조언이 아니라 참고용 분석이며 특정 매수/매도를 권유하지 않는다는
점을 리포트 끝에 한 줄로 명시하세요.
"""


def list_summaries_between(ticker: str, start: datetime, end: datetime) -> list[dict]:
    """특정 티커에 대해 [start, end] 구간(저장 시각 created_at 기준)의 글만 최신순으로 반환한다."""
    ticker = ticker.strip().upper()
    with get_session() as session:
        rows = (
            session.query(ThreadsSummary)
            .filter(ThreadsSummary.created_at >= start, ThreadsSummary.created_at <= end)
            .order_by(ThreadsSummary.created_at.desc())
            .all()
        )
        result = [_row_to_dict(r) for r in rows]
    return [r for r in result if ticker in r["tickers"]]


def _fallback_weekly_digest(ticker: str, posts: list[dict]) -> str:
    """AI 없이(또는 실패 시) 저장된 글을 시간순으로 나열만 하는 최소 대체 리포트."""
    lines = [
        f"[자동 리포트 실패 - 규칙 기반 다이제스트 사용] GEMINI_API_KEY가 설정되지 않았거나 API "
        f"호출에 실패해, {ticker} 관련 저장 글 {len(posts)}건의 요약만 시간순으로 나열합니다. "
        "종합 인사이트(테마/정서변화/촉매·리스크)는 생성되지 않았습니다.",
        "",
    ]
    for p in posts:
        summary = p["ai_summary"] or p["raw_text"][:150]
        lines.append(f"- {p['created_at'].strftime('%Y-%m-%d %H:%M')}: {summary}")
    return "\n".join(lines)


def generate_weekly_report(ticker: str, days: int = 7) -> dict:
    """지정된 티커에 대해 최근 N일간 저장된 글을 모아 AI 인사이트 리포트를 생성한다.

    단순 요약이 아니라 여러 글을 종합했을 때 드러나는 테마/정서 변화/촉매·리스크/합의-소수의견/
    관찰포인트를 뽑아내는 것이 목표다 (WEEKLY_REPORT_SYSTEM_PROMPT 참고). 복잡한 종합 추론이
    필요한 작업이라 gemini_client.COMPLEX_TASK_MODELS를 사용한다(단순 티커 인식/요약보다 상위 모델).

    Returns:
        {"ticker": str, "period_start": datetime, "period_end": datetime,
         "post_count": int, "report": str}

    저장된 글이 없어도, GEMINI_API_KEY가 없어도, API 호출이 실패해도 예외를 던지지 않는다
    (기존 analyze_text()와 동일한 관례).
    """
    ticker = ticker.strip().upper()
    period_end = datetime.utcnow()
    period_start = period_end - timedelta(days=days)

    posts = list_summaries_between(ticker, period_start, period_end)
    posts = list(reversed(posts))  # 정서 변화 흐름을 추적하려면 오래된 것부터 시간순이어야 한다

    if not posts:
        return {
            "ticker": ticker,
            "period_start": period_start,
            "period_end": period_end,
            "post_count": 0,
            "report": f"최근 {days}일간 {ticker}에 태깅된 저장 글이 없습니다. "
            "먼저 '새 글 분석' 탭에서 관련 글을 저장해주세요.",
        }

    if not gemini_client.has_api_key():
        return {
            "ticker": ticker,
            "period_start": period_start,
            "period_end": period_end,
            "post_count": len(posts),
            "report": _fallback_weekly_digest(ticker, posts),
        }

    try:
        payload_lines = [
            f"[{p['created_at'].strftime('%Y-%m-%d %H:%M')}] {p['ai_summary'] or p['raw_text'][:300]}"
            for p in posts
        ]
        contents = (
            f"티커: {ticker}\n기간: {period_start.date()} ~ {period_end.date()}\n"
            f"저장된 글 {len(posts)}건(시간순, 오래된 것부터):\n\n" + "\n\n".join(payload_lines)
        )
        response = gemini_client.generate_content(
            models=gemini_client.COMPLEX_TASK_MODELS,
            contents=contents,
            system_instruction=WEEKLY_REPORT_SYSTEM_PROMPT,
        )
        report = response.text or _fallback_weekly_digest(ticker, posts)
        return {
            "ticker": ticker,
            "period_start": period_start,
            "period_end": period_end,
            "post_count": len(posts),
            "report": report,
        }
    except Exception as e:
        return {
            "ticker": ticker,
            "period_start": period_start,
            "period_end": period_end,
            "post_count": len(posts),
            "report": f"[AI 호출 실패: {e}] " + _fallback_weekly_digest(ticker, posts),
        }


def save_weekly_report(ticker: str, period_start: datetime, period_end: datetime, post_count: int, report_text: str) -> int:
    """생성된 주간 리포트를 저장한다 (같은 티커에 여러 번 생성 가능, 히스토리로 누적).

    저장 시점의 종가를 price_at_generation에 함께 기록해, 나중에 generate_report_feedback()이
    "그때 이 가격에서 실제로 어떻게 됐는지"를 계산할 수 있게 한다 (가격 조회 실패해도 저장은 계속됨).

    Returns:
        생성된 ThreadsWeeklyReport 의 id.
    """
    ticker = ticker.strip().upper()
    try:
        price = get_latest_price(ticker)
    except Exception:
        price = None

    with get_session() as session:
        row = ThreadsWeeklyReport(
            ticker=ticker,
            period_start=period_start,
            period_end=period_end,
            post_count=post_count,
            report_text=report_text,
            price_at_generation=price,
        )
        session.add(row)
        session.flush()
        return row.id


def _report_row_to_dict(r: ThreadsWeeklyReport) -> dict:
    return {
        "id": r.id,
        "ticker": r.ticker,
        "period_start": r.period_start,
        "period_end": r.period_end,
        "post_count": r.post_count,
        "report_text": r.report_text,
        "price_at_generation": r.price_at_generation,
        "created_at": r.created_at,
        "feedback_text": r.feedback_text,
        "feedback_price": r.feedback_price,
        "feedback_generated_at": r.feedback_generated_at,
    }


def list_weekly_reports(ticker: str, limit: int = 20) -> list[dict]:
    """특정 티커의 주간 리포트 히스토리를 최신순으로 반환한다."""
    ticker = ticker.strip().upper()
    with get_session() as session:
        rows = (
            session.query(ThreadsWeeklyReport)
            .filter(ThreadsWeeklyReport.ticker == ticker)
            .order_by(ThreadsWeeklyReport.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_report_row_to_dict(r) for r in rows]


def get_weekly_report(report_id: int) -> Optional[dict]:
    """주간 리포트 하나를 id로 조회한다. 없으면 None."""
    with get_session() as session:
        row = session.get(ThreadsWeeklyReport, report_id)
        return _report_row_to_dict(row) if row is not None else None


def delete_weekly_report(report_id: int) -> None:
    """주간 리포트를 삭제한다."""
    with get_session() as session:
        row = session.get(ThreadsWeeklyReport, report_id)
        if row is not None:
            session.delete(row)


# ==============================================================================
# 리포트 사후 검증(회고) 피드백: 시간이 지난 뒤 그 리포트가 실제로 얼마나 맞았는지
# 가격 변화와 함께 AI가 되짚어본다. "약 한 달 정도 지났을 때"처럼 사용자가 원하는
# 아무 시점에나 버튼으로 트리거할 수 있다 (자동 스케줄은 없음 — 시점 선택은 사용자 몫).
# ==============================================================================

FEEDBACK_SYSTEM_PROMPT = """\
당신은 과거에 자신이 작성한 투자 리포트를 사후 검증(post-mortem review)하는 시니어 애널리스트입니다.

과거 특정 시점에 작성된 주간 인사이트 리포트 원문과, 그 이후 실제 주가가 어떻게 움직였는지(기준가/
현재가/변화율/경과일)를 전달할 것입니다. 이 리포트를 다시 요약하지 말고, 리포트의 내용이 실제로
얼마나 들어맞았는지를 냉정하게 평가하세요.

다음 구조로 한국어 회고를 작성하세요:

1. **방향성 평가**: 리포트의 전반적 톤(낙관/비관/중립)과 실제 주가 방향이 일치했는지, 그리고
   그 정도(변화율)가 리포트의 어조에 비해 과했는지/부족했는지 평가하세요.
2. **적중한 부분**: 리포트에서 언급한 테마·촉매·리스크·관찰 포인트 중 실제로 유효했던 것을
   구체적으로 짚어주세요 (근거 없이 "잘 맞았다"고만 하지 말 것).
3. **빗나간 부분**: 반대로 언급했지만 실현되지 않았거나, 리포트가 놓친 요인이 있다면 짚어주세요.
   과도하게 자기방어적으로 쓰지 말고 솔직하게 평가하세요.
4. **다음에 참고할 점**: 이번 회고에서 얻을 수 있는, 다음 리포트 작성이나 판단에 참고할 만한
   교훈을 1~2개 제시하세요.

경과일이 아직 짧다면(예: 2주 미만) 그 사실을 서두에 명시하고 판단을 신중히 하세요. 투자 조언이
아니라 참고용 회고임을 끝에 한 줄로 명시하세요.
"""


def _fallback_feedback(price_at_generation: Optional[float], current_price: Optional[float], elapsed_days: int) -> str:
    if price_at_generation is None or current_price is None:
        return (
            "[자동 회고 실패 - 가격 데이터 부족] GEMINI_API_KEY가 설정되지 않았거나 API 호출에 "
            "실패했고, 기준가/현재가 중 일부를 조회하지 못해 정량적 비교도 제공할 수 없습니다."
        )
    change_pct = (current_price / price_at_generation - 1) * 100
    return (
        "[자동 회고 실패 - 정량 데이터만 표시] GEMINI_API_KEY가 설정되지 않았거나 API 호출에 실패해 "
        f"가격 변화만 보여드립니다. 리포트 생성 시점 가격 {price_at_generation:,.2f} → 현재가 "
        f"{current_price:,.2f} ({elapsed_days}일 경과, {change_pct:+.1f}%)."
    )


def generate_report_feedback(report_id: int) -> dict:
    """저장된 주간 리포트를 사후 검증(회고)한다: 그때 가격 대비 지금 가격이 어떻게 됐고,
    리포트의 테마/촉매/리스크/관찰 포인트가 실제로 얼마나 들어맞았는지 AI가 평가한다.

    Returns:
        {"feedback": str, "price_at_generation": float|None, "current_price": float|None,
         "price_change_pct": float|None, "elapsed_days": int}

    리포트가 없으면 ValueError. 그 외에는(가격 조회 실패, API 키 없음/실패) 예외를 던지지 않고
    _fallback_feedback 으로 대체한다.
    """
    report = get_weekly_report(report_id)
    if report is None:
        raise ValueError(f"리포트(id={report_id})를 찾을 수 없습니다.")

    now = datetime.utcnow()
    elapsed_days = (now - report["created_at"]).days
    price_at_generation = report["price_at_generation"]
    try:
        current_price = get_latest_price(report["ticker"])
    except Exception:
        current_price = None

    price_change_pct = None
    if price_at_generation is not None and current_price is not None and price_at_generation:
        price_change_pct = (current_price / price_at_generation - 1) * 100

    if not gemini_client.has_api_key():
        feedback = _fallback_feedback(price_at_generation, current_price, elapsed_days)
    else:
        try:
            price_line = (
                f"기준가(리포트 생성 시점): {price_at_generation:,.2f}\n현재가: {current_price:,.2f}\n"
                f"변화율: {price_change_pct:+.1f}%"
                if price_change_pct is not None
                else "가격 데이터를 일부 조회하지 못했습니다 (참고용으로만 활용하세요)."
            )
            contents = (
                f"티커: {report['ticker']}\n리포트 작성일: {report['created_at'].strftime('%Y-%m-%d')} "
                f"({elapsed_days}일 경과)\n{price_line}\n\n[원본 리포트]\n{report['report_text']}"
            )
            response = gemini_client.generate_content(
                models=gemini_client.COMPLEX_TASK_MODELS,
                contents=contents,
                system_instruction=FEEDBACK_SYSTEM_PROMPT,
            )
            feedback = response.text or _fallback_feedback(price_at_generation, current_price, elapsed_days)
        except Exception as e:
            feedback = f"[AI 호출 실패: {e}] " + _fallback_feedback(price_at_generation, current_price, elapsed_days)

    return {
        "feedback": feedback,
        "price_at_generation": price_at_generation,
        "current_price": current_price,
        "price_change_pct": price_change_pct,
        "elapsed_days": elapsed_days,
    }


def save_report_feedback(report_id: int, feedback_text: str, feedback_price: Optional[float]) -> None:
    """생성된 회고 피드백을 리포트에 저장한다 (다시 생성하면 최신값으로 덮어씀)."""
    with get_session() as session:
        row = session.get(ThreadsWeeklyReport, report_id)
        if row is None:
            raise ValueError(f"리포트(id={report_id})를 찾을 수 없습니다.")
        row.feedback_text = feedback_text
        row.feedback_price = feedback_price
        row.feedback_generated_at = datetime.utcnow()
