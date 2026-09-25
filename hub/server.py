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

LOGIN_PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Quant 관제 센터 로그인</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing:border-box; }
  body { margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         background:radial-gradient(1200px 600px at 50% -10%,#1b2540 0%,#0f1115 60%);
         color:#e6e6e6; font-family:-apple-system,"Segoe UI","Noto Sans KR",sans-serif; padding:1.5rem; }
  .box { width:100%; max-width:380px; background:#181b21; border:1px solid #2a2e37;
         border-radius:16px; padding:2rem 1.75rem; box-shadow:0 20px 50px rgba(0,0,0,.45); }
  .logo { width:44px; height:44px; border-radius:12px; background:#4c7dff; display:flex;
          align-items:center; justify-content:center; font-weight:700; font-size:1.3rem; margin-bottom:1rem; }
  h1 { font-size:1.35rem; margin:0 0 .25rem; }
  p.sub { color:#9aa0a8; font-size:.88rem; margin:0 0 1.5rem; }
  label { display:block; font-size:.78rem; color:#9aa0a8; margin:0 0 .35rem; }
  input { width:100%; padding:.75rem .9rem; margin-bottom:1rem; background:#0f1115; color:inherit;
          border:1px solid #2a2e37; border-radius:10px; font-size:1rem; outline:none;
          transition:border-color .15s, box-shadow .15s; }
  input:focus { border-color:#4c7dff; box-shadow:0 0 0 3px rgba(76,125,255,.25); }
  button { width:100%; padding:.8rem; border:0; border-radius:10px; background:#4c7dff; color:#fff;
           font-size:1rem; font-weight:600; cursor:pointer; transition:background .15s; }
  button:hover { background:#6390ff; }
  button:disabled { opacity:.6; cursor:default; }
  .err { min-height:1.2rem; color:#f87171; font-size:.85rem; margin:-.25rem 0 .75rem; }
</style></head><body>
<form class="box" id="f" autocomplete="on">
  <div class="logo">Q</div>
  <h1>Quant VM 관제 센터</h1>
  <p class="sub">계속하려면 로그인하세요.</p>
  <label for="u">아이디</label>
  <input id="u" name="username" autocomplete="username" autocapitalize="none" required autofocus>
  <label for="p">비밀번호</label>
  <input id="p" name="password" type="password" autocomplete="current-password" required>
  <div class="err" id="e" role="alert"></div>
  <button id="b" type="submit">로그인</button>
</form>
<script>
(function () {
  var f = document.getElementById("f"), e = document.getElementById("e"), b = document.getElementById("b");
  function dest() {
    var n = new URLSearchParams(location.search).get("next");
    try {
      var u = new URL(n, location.origin), h = location.hostname;
      if (u.protocol === "https:" && (u.hostname === h || u.hostname.endsWith("." + h))) return u.href;
    } catch (x) {}
    return "/";
  }
  f.addEventListener("submit", function (ev) {
    ev.preventDefault();
    e.textContent = ""; b.disabled = true; b.textContent = "확인 중...";
    var bytes = new TextEncoder().encode(f.username.value + ":" + f.password.value), bin = "";
    bytes.forEach(function (c) { bin += String.fromCharCode(c); });
    fetch("/_login", { method: "POST", credentials: "same-origin", headers: { Authorization: "Basic " + btoa(bin) } })
      .then(function (r) {
        if (r.ok) { location.replace(dest()); return; }
        e.textContent = r.status === 401 ? "아이디 또는 비밀번호가 올바르지 않습니다." : "로그인에 실패했습니다 (" + r.status + ").";
        f.password.value = ""; f.password.focus(); b.disabled = false; b.textContent = "로그인";
      })
      .catch(function () {
        e.textContent = "서버에 연결하지 못했습니다."; b.disabled = false; b.textContent = "로그인";
      });
  });
})();
</script></body></html>"""


# 사용 설명서 진입 카드 — 슬롯(systemd 유닛)이 아니라 허브 자체 기능이라 SLOTS 와 별개로 항상 맨 앞에 둔다.
GUIDE_CARD = (
    '<a class="card" href="/guide" style="border-color:#4c7dff">'
    '<h2>📖 사용 설명서<span class="kind">guide</span></h2>'
    '<p>대시보드를 어떻게 쓰는지, 각 화면과 엔진 모듈이 무엇인지, 자동 잡과 알림은 어떻게 읽는지 정리했습니다. '
    '엔진이 업데이트되면 함께 갱신됩니다.</p>'
    '<span class="badge active">항상 최신</span></a>'
)


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
        '<a class="back" style="float:right" href="#" '
        'onclick="fetch(\'/_logout\',{method:\'POST\'}).then(function(){location.href=\'/login\'});return false">'
        '로그아웃</a><h1>Quant VM 관제 센터</h1>'
        '<p class="subtitle">이 서버에서 돌고 있는 앱과 엔진들. 슬롯을 누르면 해당 웹 또는 '
        '상태 화면으로 이동합니다.</p>'
        f'<div class="grid">{GUIDE_CARD}{"".join(cards)}</div>'
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
        elif path == "/login":
            self._send_html(LOGIN_PAGE)
        elif path in ("/guide", "/guide/"):
            from hub.guide import render_guide_page

            self._send_html(render_guide_page())
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
