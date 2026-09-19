"""오늘의 브리핑 — 매일 밤 스케줄러가 마지막에 생성해 텔레그램으로 보내는 단일 요약 HTML.

사용자는 이 프로젝트를 거의 전적으로 폰 텔레그램 봇으로 접한다(데스크톱 Streamlit UI를 직접 여는
경우는 드묾) — 그런데 지금까지는 신호변경/리밸런싱/실적/알파감쇠/데이터무결성 등 매일 밤 여러
잡이 각각 따로 텔레그램 메시지를 보내 흩어져 있었다. 이 모듈은 그 잡들이 이미 계산·저장해둔 결과를
"오늘 밤 확인이 필요한 게 있는가"를 30초 안에 훑어볼 수 있는 한 장짜리 HTML로 모은다.

이 모듈은 새 계산을 하지 않는다(알파 감쇠 백테스트 재실행 제외) — 전부 다른 잡이 이미 계산·저장한
결과를 읽기만 하는 read-only 소비자다. core.champion_strategy/core.data_integrity의 기존 함수를
그대로 재사용하고, 파일 저장/전송 패턴은 send_weekly_report()를 그대로 따른다.

stdlib + pandas만 사용(차트 라이브러리 없음) — 이 HTML은 텔레그램 파일 첨부로 전달되어 네트워크
접근 없이 렌더링되어야 하므로 외부 리소스를 전혀 참조하지 않는다.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from core.champion_strategy import (
    CHAMPION_REPORT_DIR,
    compute_champion_alpha_decay,
    compute_live_collar_state,
    get_current_holdings,
    get_upcoming_earnings,
    list_champion_correlation_snapshots,
)
from core.data_integrity import run_integrity_checks

# core.theme._DARK 팔레트와 통일 (research-terminal 다크 톤)
_BG = "#0d0e12"
_BG_SECONDARY = "#15161b"
_TEXT = "#d7d8db"
_TEXT_MUTED = "#888b93"
_BORDER = "#262830"
_ACCENT = "#2962ff"
_GREEN = "#26a69a"
_RED = "#ef5350"
_YELLOW = "#f5a623"

EARNINGS_WITHIN_DAYS = 5


def _section(title: str, body_html: str, *, accent: str | None = None) -> str:
    border = f"border-left:3px solid {accent};" if accent else ""
    return f'''<div class="section" style="{border}">
<h2>{title}</h2>
{body_html}
</div>'''


def _status_line(anomaly_count: int, decay_flagged: bool) -> tuple[str, str]:
    """(문구, 색상) — critical/warning 이상 또는 알파 감쇠 감지 시 red/yellow, 아니면 green."""
    if anomaly_count > 0:
        return (f"오늘 확인이 필요한 이상 {anomaly_count}건 감지됨", _RED)
    if decay_flagged:
        return ("데이터 이상은 없지만 알파 감쇠가 감지됨 — 확인 권장", _YELLOW)
    return ("특이사항 없음 — 정상 운영 중", _GREEN)


def _anomalies_section(anomalies: list[dict]) -> str:
    if not anomalies:
        return ""
    critical = [a for a in anomalies if a["severity"] == "critical"]
    warning = [a for a in anomalies if a["severity"] == "warning"]
    rows = "".join(
        f'<li><span class="tag" style="background:{_RED if a["severity"] == "critical" else _YELLOW};'
        f'color:#0d0e12">{a["severity"]}</span> <code>{a["check"]}</code>: {a["detail"]}</li>'
        for a in critical + warning
    )
    return _section(
        f"🚨 데이터 이상 (critical {len(critical)} / warning {len(warning)})",
        f'<ul class="anomaly-list">{rows}</ul>',
        accent=_RED,
    )


def _decay_section(decay: dict | None) -> str:
    if decay is None:
        return _section("알파 감쇠 상태", '<p class="muted">데이터 없음</p>')
    ratio = decay.get("decay_ratio")
    ratio_txt = f"{ratio:.2f}" if ratio is not None else "N/A"
    flagged = decay.get("is_decayed")
    badge = (
        f'<span class="tag" style="background:{_RED};color:#0d0e12">감쇠 감지</span>'
        if flagged
        else f'<span class="tag" style="background:{_GREEN};color:#0d0e12">정상</span>'
    )
    metric = decay.get("metric", "sharpe")
    full_m = decay.get("full_metrics", {}).get(metric)
    recent_m = decay.get("recent_metrics", {}).get(metric)
    full_txt = f"{full_m:.2f}" if isinstance(full_m, (int, float)) else "N/A"
    recent_txt = f"{recent_m:.2f}" if isinstance(recent_m, (int, float)) else "N/A"
    body = (
        f'<p>{badge} decay_ratio=<code>{ratio_txt}</code> '
        f'({metric}: 전체 <code>{full_txt}</code> → 최근 <code>{recent_txt}</code>)</p>'
    )
    return _section("알파 감쇠 상태", body, accent=_RED if flagged else None)


def _holdings_section(holdings: dict | None) -> str:
    if not holdings:
        return _section("현재 보유종목", '<p class="muted">데이터 없음 (아직 신호 캐시 없음)</p>')
    core_top4 = holdings.get("core_top4") or []
    satellite = holdings.get("satellite_selected") or []
    core_html = "".join(f"<code>{t}</code>" for t in core_top4) or '<span class="muted">없음</span>'
    sat_html = "".join(f"<code>{t}</code>" for t in satellite) or '<span class="muted">없음</span>'
    body = (
        f'<p class="muted">기준일: {holdings.get("as_of", "N/A")}</p>'
        f'<p><strong>코어 top4</strong><br>{core_html}</p>'
        f'<p><strong>새틀라이트</strong><br>{sat_html}</p>'
    )
    return _section("현재 보유종목", body)


def _correlation_section(snapshots: list[dict]) -> str:
    if not snapshots:
        return _section("보유종목 상관관계", '<p class="muted">데이터 없음</p>')
    snap = snapshots[0]
    computed_at = snap.get("computed_at")
    computed_at_txt = computed_at.strftime("%Y-%m-%d") if hasattr(computed_at, "strftime") else str(computed_at)
    labels = snap.get("labels", [])
    body = (
        f'<p class="muted">{computed_at_txt} 기준 ({", ".join(labels)})</p>'
        f'<table><tr><td>평균 상관계수</td><td class="num">{snap["avg_correlation"]:.2f}</td></tr>'
        f'<tr><td>최대 상관계수</td><td class="num">{snap["max_correlation"]:.2f}</td></tr></table>'
    )
    return _section("보유종목 상관관계", body)


def _earnings_section(earnings: list[dict]) -> str:
    if not earnings:
        return ""
    rows = "".join(
        f'<tr><td><code>{e["ticker"]}</code></td><td class="num">{e["earnings_date"]}</td></tr>'
        for e in earnings
    )
    return _section(
        f"📅 다가오는 실적 발표 ({EARNINGS_WITHIN_DAYS}거래일 이내)",
        f'<table>{rows}</table>',
        accent=_YELLOW,
    )


def _collar_section(collar: dict | None) -> str:
    if collar is None:
        return ""
    pnl = collar.get("mark_to_model_pnl_pct_of_satellite_notional")
    pnl_color = _GREEN if (pnl or 0) >= 0 else _RED
    body = (
        f'<p>롤 시작 <code>{collar.get("roll_date")}</code>, 만기까지 '
        f'<code>{collar.get("days_remaining")}</code>거래일 남음</p>'
        f'<p>마크투모델 손익(새틀라이트 명목 대비): '
        f'<span style="color:{pnl_color}">{pnl:+.3f}%</span></p>'
    )
    return _section("칼라 헤지 상태", body)


def generate_daily_briefing_html() -> str:
    """오늘의 브리핑 HTML을 하나의 self-contained 문자열로 조립한다.

    각 데이터 소스가 없거나 예외를 던져도 다른 섹션에 영향을 주지 않는다 — 개별 섹션 함수가
    None/빈 값을 "데이터 없음"으로 정직하게 표시한다.
    """
    today = date.today().isoformat()

    try:
        integrity = run_integrity_checks()
        anomalies = integrity.get("anomalies", [])
    except Exception:
        anomalies = []

    try:
        decay = compute_champion_alpha_decay()
    except Exception:
        decay = None

    try:
        holdings = get_current_holdings()
    except Exception:
        holdings = None

    try:
        corr_snapshots = list_champion_correlation_snapshots(limit=1)
    except Exception:
        corr_snapshots = []

    try:
        satellite_tickers = holdings["satellite_selected"] if holdings else []
        earnings = get_upcoming_earnings(satellite_tickers, within_days=EARNINGS_WITHIN_DAYS) if satellite_tickers else []
    except Exception:
        earnings = []

    try:
        collar = compute_live_collar_state()
    except Exception:
        collar = None

    status_text, status_color = _status_line(len(anomalies), bool(decay and decay.get("is_decayed")))

    sections = "".join([
        _anomalies_section(anomalies),
        _decay_section(decay),
        _holdings_section(holdings),
        _correlation_section(corr_snapshots),
        _earnings_section(earnings),
        _collar_section(collar),
    ])

    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>오늘의 브리핑</title>
<style>
body{{font-family:-apple-system,system-ui,sans-serif;max-width:640px;margin:0 auto;padding:1.2rem;
  background:{_BG};color:{_TEXT};line-height:1.55}}
h1{{font-size:1.3rem;margin:0 0 .2rem}}
h2{{font-size:1rem;margin:0 0 .5rem;color:{_TEXT}}}
.muted{{color:{_TEXT_MUTED}}}
.dateline{{color:{_TEXT_MUTED};font-size:.85em;margin-bottom:.6rem}}
.status{{padding:.7rem .9rem;border-radius:6px;background:{_BG_SECONDARY};border:1px solid {_BORDER};
  margin-bottom:1rem;font-weight:600}}
.section{{background:{_BG_SECONDARY};border:1px solid {_BORDER};border-radius:6px;padding:.8rem .9rem;
  margin-bottom:.8rem}}
code{{font-family:"SFMono-Regular",Consolas,monospace;background:#1b1d24;padding:.1rem .35rem;
  border-radius:3px;margin-right:.3rem;display:inline-block;margin-bottom:.2rem}}
table{{width:100%;border-collapse:collapse;font-size:.92em}}
td{{padding:.25rem .3rem;border-bottom:1px solid {_BORDER}}}
td.num{{text-align:right;font-family:"SFMono-Regular",Consolas,monospace}}
ul.anomaly-list{{padding-left:1.1rem;margin:.3rem 0}}
ul.anomaly-list li{{margin-bottom:.4rem}}
.tag{{font-size:.72em;font-weight:700;border-radius:3px;padding:.05rem .35rem;margin-right:.3rem;
  text-transform:uppercase}}
.disclaimer{{color:{_TEXT_MUTED};font-size:.78em;margin-top:1rem}}
</style></head><body>
<h1>📋 오늘의 브리핑</h1>
<p class="dateline">{today}</p>
<div class="status" style="color:{status_color}">{status_text}</div>
{sections}
<p class="disclaimer">참고용 요약이며 투자 조언이 아닙니다.</p>
</body></html>'''


def send_daily_briefing(dry_run: bool = False) -> dict:
    """generate_daily_briefing_html()을 파일로 저장하고 텔레그램 문서로 전송한다.

    send_weekly_report()와 동일한 저장경로(CHAMPION_REPORT_DIR)/전송 패턴을 따른다 — 파일명
    접두사만 daily_briefing으로 구분.

    Returns: {"path": str, "sent": bool}
    """
    CHAMPION_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = CHAMPION_REPORT_DIR / f"daily_briefing_{date.today().isoformat()}.html"
    report_path.write_text(generate_daily_briefing_html(), encoding="utf-8")
    sent = False
    if not dry_run:
        from core.telegram_notify import send_document
        sent = send_document(report_path, caption="📋 오늘의 브리핑")
    return {"path": str(report_path), "sent": sent}
