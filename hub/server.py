"""Quant VM 관제 허브 — 최상위 진입점.

nginx가 80번 포트(`/`)를 이 서버(기본 127.0.0.1:8000)로 프록시한다. 이 서버 자체는 stdlib만
사용하며(신규 의존성 없음), 각 앱/엔진의 상태를 보여주고 슬롯 클릭 시 해당 웹(Streamlit 등
자체 포트로 직접 이동) 또는 엔진 상태/리포트 페이지로 안내한다.

실행: python -m hub.server (deploy/quant-hub.service 참고)
"""

from __future__ import annotations

import html
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hub.apps_registry import SLOTS, AppSlot  # noqa: E402
from hub.status import UnitStatus, get_unit_status  # noqa: E402

HOST = "127.0.0.1"  # nginx를 거치지 않는 외부 직접 접속은 차단(방화벽에 별도 포트 개방 불필요)
PORT = 8000

PAGE_STYLE = """
<style>
  :root { color-scheme: dark; }
  body { background:#0f1115; color:#e6e6e6; font-family:-apple-system,"Segoe UI",sans-serif;
         margin:0; padding:2.5rem 1.5rem; }
  h1 { font-size:1.6rem; margin-bottom:.25rem; }
  p.subtitle { color:#9aa0a8; margin-top:0; margin-bottom:2rem; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr));
          gap:1rem; max-width:1100px; }
  .card { display:block; background:#181b21; border:1px solid #2a2e37; border-radius:12px;
          padding:1.1rem 1.3rem; text-decoration:none; color:inherit;
          transition:border-color .15s ease; }
  .card:hover { border-color:#4c7dff; }
  .card h2 { font-size:1.05rem; margin:0 0 .35rem; }
  .card p { color:#9aa0a8; font-size:.85rem; margin:0 0 .7rem; line-height:1.4; }
  .badge { display:inline-block; font-size:.72rem; padding:.15rem .55rem; border-radius:999px;
           font-weight:600; }
  .badge.active { background:#123d24; color:#4ade80; }
  .badge.inactive { background:#3d1212; color:#f87171; }
  .badge.unknown { background:#333844; color:#c9c9c9; }
  .kind { color:#5b6472; font-size:.72rem; text-transform:uppercase; letter-spacing:.05em;
          margin-left:.4rem; }
  a.back { color:#4c7dff; font-size:.85rem; text-decoration:none; }
</style>
"""


def _badge_html(status: UnitStatus) -> str:
    if not status.is_known:
        css, label = "unknown", "상태 확인 불가"
    elif status.is_active:
        css, label = "active", f"{status.active_state}/{status.sub_state}"
    else:
        css, label = "inactive", f"{status.active_state}/{status.sub_state}"
    return f'<span class="badge {css}">{html.escape(label)}</span>'


def _slot_href(slot: AppSlot, host: str) -> str:
    if slot.kind == "web":
        return f"http://{host}:{slot.port}/"
    if slot.kind == "link":
        return slot.url or "/"
    if slot.kind == "report":
        return f"/reports/{slot.id}"
    return f"/status/{slot.id}"


def render_dashboard(host: str) -> str:
    cards = []
    for slot in SLOTS:
        status = get_unit_status(slot.unit)
        href = _slot_href(slot, host)
        target = ' target="_blank" rel="noopener"' if slot.kind in ("web", "link") else ""
        cards.append(
            f'<a class="card" href="{html.escape(href)}"{target}>'
            f'<h2>{html.escape(slot.title)}<span class="kind">{html.escape(slot.kind)}</span></h2>'
            f'<p>{html.escape(slot.description)}</p>'
            f'{_badge_html(status)}'
            f'</a>'
        )
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        f'<title>Quant VM 관제 센터</title>{PAGE_STYLE}</head><body>'
        '<h1>Quant VM 관제 센터</h1>'
        '<p class="subtitle">이 서버에서 돌고 있는 앱과 엔진들. 슬롯을 누르면 해당 웹 또는 '
        '상태 화면으로 이동합니다.</p>'
        f'<div class="grid">{"".join(cards)}</div>'
        '</body></html>'
    )


def render_status_page(slot: AppSlot) -> str:
    status = get_unit_status(slot.unit)
    since = html.escape(status.since) if status.since else "정보 없음"
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        f'<title>{html.escape(slot.title)} 상태</title>{PAGE_STYLE}</head><body>'
        '<p><a class="back" href="/">&larr; 관제 센터로</a></p>'
        f'<h1>{html.escape(slot.title)}</h1>'
        f'<p class="subtitle">{html.escape(slot.description)}</p>'
        f'{_badge_html(status)}'
        f'<p style="margin-top:1rem;color:#9aa0a8;font-size:.85rem">'
        f'systemd unit: {html.escape(slot.unit)}<br>since: {since}</p>'
        '<p style="margin-top:1rem;color:#5b6472;font-size:.78rem">'
        '이 엔진은 별도 웹 UI 없이 백그라운드로 동작합니다(결과는 텔레그램 알림으로 발송됩니다).'
        '</p></body></html>'
    )


def render_no_report_page(slot: AppSlot) -> str:
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        f'<title>{html.escape(slot.title)}</title>{PAGE_STYLE}</head><body>'
        '<p><a class="back" href="/">&larr; 관제 센터로</a></p>'
        f'<h1>{html.escape(slot.title)}</h1>'
        '<p class="subtitle">아직 생성된 리포트가 없습니다.</p>'
        '</body></html>'
    )


def find_slot(slot_id: str, *, kind: str | None = None) -> AppSlot | None:
    for slot in SLOTS:
        if slot.id == slot_id and (kind is None or slot.kind == kind):
            return slot
    return None


def latest_report_path(slot: AppSlot) -> Path | None:
    if not slot.report_glob:
        return None
    matches = sorted(
        PROJECT_ROOT.glob(slot.report_glob), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return matches[0] if matches else None


class HubRequestHandler(BaseHTTPRequestHandler):
    server_version = "QuantHub/1.0"

    def log_message(self, format: str, *args) -> None:  # noqa: A002 (BaseHTTPRequestHandler 시그니처)
        pass  # 접속 로그는 journalctl 대신 systemd 자체 stdout 캡처에 맡기지 않고 조용히 무시

    def _send_html(self, body: str, status: int = 200) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        host = (self.headers.get("Host") or "").split(":")[0] or "localhost"

        if path in ("/", ""):
            self._send_html(render_dashboard(host))
        elif path == "/healthz":
            self._send_html("ok")
        elif path.startswith("/status/"):
            slot = find_slot(path.removeprefix("/status/"))
            self._send_html(render_status_page(slot)) if slot else self._send_html("not found", 404)
        elif path.startswith("/reports/"):
            slot = find_slot(path.removeprefix("/reports/"), kind="report")
            if slot is None:
                self._send_html("not found", 404)
                return
            report_path = latest_report_path(slot)
            if report_path is None:
                self._send_html(render_no_report_page(slot))
            else:
                self._send_html(report_path.read_text(encoding="utf-8"))
        else:
            self._send_html("not found", 404)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), HubRequestHandler)
    print(f"Quant hub listening on {HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
