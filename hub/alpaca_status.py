"""관제 허브의 Alpaca paper 화면 — 스케줄러 잡들이 남긴 결과 파일만 읽어 보여준다(stdlib 전용, 네트워크 없음).

읽는 파일(없으면 '아직 없음'으로 표시):
- data/verification/alpaca_*.json      P0 읽기 전용 검증(00:40 KST)
- data/cache/paper_tracking.json       P1 추적오차(00:46 KST)
- data/cache/cost_calibration.json     P2 실측 비용(00:42 KST)
- data/paper_auto/state.json           P3 자동 주문 기록(화~토 06:10 KST)
- data/process_toggles.json            잡 켜짐/꺼짐(core.process_registry)
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent

JOBS = [
    ("alpaca_verification_bootstrap", "P0 검증", "매일 00:40"),
    ("account_snapshot_sync", "계좌 스냅샷", "매일 00:35"),
    ("cost_calibration_refresh", "P2 비용 보정", "매일 00:42"),
    ("paper_tracking_refresh", "P1 추적오차", "매일 00:46"),
    ("paper_auto_trade", "P3 자동 주문", "화~토 06:10"),
]


def _read(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _latest_verification(root: Path) -> Optional[dict]:
    files = sorted((root / "data" / "verification").glob("alpaca_*.json"), reverse=True)
    return _read(files[0]) if files else None


def _enabled(key: str) -> Optional[bool]:
    try:
        from core.process_registry import is_enabled

        return is_enabled(key)
    except Exception:  # noqa: BLE001
        return None


def _pill(text: str, tone: str) -> str:
    return f'<span class="badge {tone}">{html.escape(text)}</span>'


def _row(label: str, value: str) -> str:
    return f'<tr><th>{html.escape(label)}</th><td>{value}</td></tr>'


def _esc(v: Any) -> str:
    return html.escape("—" if v is None else str(v))


def collect(root: Path = PROJECT_ROOT) -> dict:
    return {
        "verification": _latest_verification(root),
        "tracking": _read(root / "data" / "cache" / "paper_tracking.json"),
        "cost": _read(root / "data" / "cache" / "cost_calibration.json"),
        "auto_state": _read(root / "data" / "paper_auto" / "state.json"),
        "jobs": [(k, label, when, _enabled(k)) for k, label, when in JOBS],
    }


def card_badge(root: Path = PROJECT_ROOT) -> str:
    v = _latest_verification(root)
    if v is None:
        return _pill("검증 대기", "unknown")
    overall = v.get("overall") or v.get("status")
    return _pill(f"검증 {overall}", "active" if overall == "PASS" else "inactive")


def render_body(data: dict) -> str:
    parts = ['<p class="subtitle">전략 검증용 paper(모의) 계좌. 실거래 경로 없음. 아래는 스케줄러가 남긴 최신 결과입니다.</p>']

    v = data["verification"]
    rows = []
    if v is None:
        rows.append(_row("상태", _pill("아직 실행 전", "unknown") + " 다음 00:40 KST에 자동 실행"))
    else:
        ok = v.get("overall") == "PASS"
        rows.append(_row("전체", _pill(str(v.get("overall") or v.get("status")), "active" if ok else "inactive")))
        rows.append(_row("실행 시각", _esc(v.get("generated_at"))))
        for name, c in (v.get("checks") or {}).items():
            tone = "active" if c.get("verdict") == "PASS" else "inactive"
            detail = _esc(c.get("summary"))
            if c.get("failing"):
                detail += "<br><small>" + "<br>".join(html.escape(f) for f in c["failing"][:5]) + "</small>"
            rows.append(_row(name, _pill(c.get("verdict", "?"), tone) + " " + detail))
    parts.append(f'<h2>P0 실 API 검증</h2><table>{"".join(rows)}</table>')

    t = data["tracking"]
    rows = []
    if not t or not t.get("n_intervals"):
        n_s = (t or {}).get("n_snapshots", 0)
        rows.append(_row("상태", f"비교 구간 없음 (계좌 스냅샷 {_esc(n_s)}건) — 스냅샷이 이틀 이상 쌓이면 계산"))
    else:
        rows += [_row("비교 구간", _esc(t["n_intervals"])),
                 _row("paper 누적", _esc(f"{t['paper_cum_return_pct']:+.2f}%")),
                 _row("챔피언 가상 누적", _esc(f"{t['champion_cum_return_pct']:+.2f}%")),
                 _row("괴리", _esc(f"{t['cum_gap_pct_points']:+.2f}%p")),
                 _row("추적오차(연)", _esc(f"{t['tracking_error_annual_pct']:.2f}%") if t.get("tracking_error_annual_pct") is not None
                      else f"표본 부족 (구간 {t.get('min_intervals_for_te', 20)}개 필요)")]
        ctx = t.get("context") or {}
        if "following" in ctx:
            rows.append(_row("계좌가 전략을 따르는 중", "예" if ctx["following"] else "아니오 (포지션 없음 — 괴리는 실행 품질이 아님)"))
    parts.append(f'<h2>P1 추적오차</h2><table>{"".join(rows)}</table>')

    c = data["cost"]
    if not c:
        cost = "아직 없음"
    elif c.get("status") == "ok":
        cost = f"실측 슬리피지 편도 {_esc((c.get('scenario') or {}).get('slippage_bps'))}bp (체결 {_esc(c.get('n'))}건)"
    else:
        cost = f"{_esc(c.get('reason') or c.get('status'))} (체결 {_esc(c.get('n'))}건, 30건부터 사용)"
    parts.append(f'<h2>P2 실측 비용</h2><table>{_row("상태", cost)}</table>')

    s = data["auto_state"] or {}
    rows = []
    for day, rec in sorted(s.items(), reverse=True)[:10]:
        rows.append(_row(day, _esc(rec.get("status")) + (f" — 주문 {_esc(rec.get('n_orders'))}건 {_esc(rec.get('states'))}"
                                                           if rec.get("status") == "submitted" else "")))
    if not rows:
        rows.append(_row("기록", "아직 없음"))
    parts.append(f'<h2>P3 자동 주문 기록</h2><table>{"".join(rows)}</table>')

    rows = []
    for key, label, when, on in data["jobs"]:
        pill = _pill("켜짐", "active") if on else _pill("꺼짐", "inactive") if on is False else _pill("?", "unknown")
        rows.append(_row(f"{label} ({when} KST)", pill + f" <small>{html.escape(key)}</small>"))
    parts.append(f'<h2>잡 상태</h2><table>{"".join(rows)}</table>'
                 '<p class="subtitle" style="margin-top:.6rem">켜고 끄기: 텔레그램 /processes</p>')
    return "".join(parts)
