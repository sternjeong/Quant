"""Notion 슬롯 — 한 번 누르면 VM 크롬에서 (자동 로그인된) 내 Notion 을 보여 준다.

    GET  /notion          진행 화면 → 끝나면 VM 크롬 화면(noVNC)을 그대로 띄운다
    POST /notion/start    로그인 스크립트 시작(같은 출처 POST 만)
    GET  /notion/status   진행 상태(JSON)

허브(quant 계정)는 ubuntu 계정의 Notion/Gmail 비밀값을 읽지 못한다. 그래서 실제 로그인은 gpu-hub 서비스(ubuntu,
127.0.0.1:8765 전용)가 ~/repos/notion/notion_login.js 로 하고, 허브는 그 상태만 중계한다.
VM 크롬 화면은 nginx 의 /vm-browser/ (→ 127.0.0.1:6080 noVNC) 로 보이며, 허브와 같은 로그인 뒤에만 있다
(deploy/setup_gateway.sh). 로그인된 브라우저이므로 인증 없는 경로로 절대 내보내지 않는다.
"""

from __future__ import annotations

import html
import json
import urllib.error
import urllib.request

from core import planner as pl
from hub import ui

GPU_HUB = "http://127.0.0.1:8765"
VIEWER_URL = "/vm-browser/vnc.html?autoconnect=1&resize=scale&reconnect=1&path=vm-browser/websockify"
ENV_HELP = (
    "Gmail 앱 비밀번호가 없어 인증코드를 자동으로 넣지 못했습니다. 지금은 아래 화면에서 메일로 온 코드를 직접 입력하면 됩니다. "
    "다음부터 자동으로 하려면: Google 계정 → 보안 → 2단계 인증 → <b>앱 비밀번호</b>에서 16자리를 만든 뒤, "
    "VM 에서 <code>~/.config/notion-login/env</code> 의 <code>GMAIL_APP_PASSWORD=</code> 뒤에 공백 없이 넣으세요 "
    "(파일 권한 600 유지, 다른 곳에 붙여 넣지 마세요)."
)


def _gpu_hub(path: str, payload: dict | None = None, timeout: float = 15) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(GPU_HUB + path, data=data, method="POST" if data is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return {"state": "error", "done": True, "message": json.loads(e.read().decode()).get("error", str(e))}
        except ValueError:
            return {"state": "error", "done": True, "message": f"gpu-hub 오류 {e.code}"}
    except (OSError, ValueError):
        return {"state": "error", "done": True,
                "message": "gpu-hub 서비스(127.0.0.1:8765)에 연결하지 못했습니다. `systemctl status gpu-hub` 를 확인하세요."}


def start() -> dict:
    return _gpu_hub("/api/notion/login", {"url": pl.notion_url()})


def status() -> dict:
    return _gpu_hub("/api/notion/status", timeout=5)


def card_badge() -> str:
    return ui.pill("자동 로그인", "info")


_SCRIPT = """
<script>
(function () {
  var box = document.getElementById("nl-msg"), help = document.getElementById("nl-help"),
      view = document.getElementById("nl-view"), frame = document.getElementById("nl-frame"), shown = false;
  function show() {
    if (shown) return; shown = true;
    view.hidden = false; frame.src = frame.getAttribute("data-src");
  }
  function render(s) {
    box.textContent = s.message || s.state || "";
    box.className = "note " + ({ok: "ok", already_logged_in: "ok", need_app_password: "warn"}[s.state] ||
                               (s.done ? "bad" : ""));
    help.hidden = s.state !== "need_app_password";
    if (s.done || s.state === "need_app_password") show();
  }
  function poll() {
    fetch("/notion/status", {credentials: "same-origin", cache: "no-store"}).then(function (r) { return r.json(); })
      .then(function (s) { render(s); if (!s.done) setTimeout(poll, 2000); })
      .catch(function () { setTimeout(poll, 4000); });
  }
  fetch("/notion/start", {method: "POST", credentials: "same-origin"}).then(function (r) { return r.json(); })
    .then(function (s) { render(s); if (!s.done) setTimeout(poll, 1500); })
    .catch(function () { box.textContent = "시작 요청 실패"; box.className = "note bad"; });
})();
</script>
"""


def render_page() -> str:
    E = html.escape
    external = pl.notion_url()
    body = (
        "<h1>Notion</h1>"
        '<p class="lead">VM 크롬에서 내 Notion 을 엽니다. 로그인이 풀려 있으면 자동으로 다시 로그인합니다.</p>'
        '<p id="nl-msg" class="note" role="status" aria-live="polite">로그인 확인 중…</p>'
        f'<div id="nl-help" hidden>{ui.callout(ENV_HELP, icon="🔑", tone="warn")}</div>'
        '<section id="nl-view" hidden>'
        f'<p class="meta"><a href="{E(VIEWER_URL)}" target="_blank" rel="noopener">VM 크롬 화면 전체 창으로 열기 ↗</a>'
        f' · <a href="{E(external)}" target="_blank" rel="noopener noreferrer">내 브라우저에서 Notion 열기 ↗</a></p>'
        f'<iframe id="nl-frame" data-src="{E(VIEWER_URL)}" title="VM 크롬 화면" '
        'style="width:100%;height:78vh;border:1px solid #2a2e37;border-radius:10px;background:#000"></iframe>'
        "</section>"
    )
    page = ui.page("Notion", body, crumbs=(("/", "개요"), ("", "Notion")))
    return page.replace("</body>", _SCRIPT + "</body>")
