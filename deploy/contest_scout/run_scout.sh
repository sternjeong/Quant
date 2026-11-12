#!/usr/bin/env bash
# 주간 해커톤·AI 대회 탐색. quant-contest-scout.service 가 ubuntu 계정으로 실행한다
# (매주 월 09:00 KST 타이머, 또는 관제 센터 '지금 찾기'가 만든 run-request 파일을 .path 유닛이 감지).
#
# Claude 는 tmux 세션 'contest-scout' 안에서 돈다 — `tmux attach -t contest-scout` 로 진행을 볼 수 있고,
# 끝난 뒤에도 창이 남아 마지막 출력을 다시 볼 수 있다(다음 실행 때 지우고 새로 만든다).
# Claude 는 웹 검색·열람과 SCOUT_DIR/draft.json 쓰기만 할 수 있다(Bash 금지). finalize.py 가 검사해 latest.json 으로 옮긴다.
set -euo pipefail

SCOUT_DIR="${SCOUT_DIR:-/srv/contests/.scout}"
SESSION="${SCOUT_TMUX_SESSION:-contest-scout}"
MODEL="${SCOUT_MODEL:-sonnet}"
TIMEOUT_MIN="${SCOUT_TIMEOUT_MIN:-120}"
HERE="$(cd "$(dirname "$0")" && pwd)"
export PATH="/opt/node22/bin:/usr/local/bin:/usr/bin:/bin"

status() {  # status <state> <message>
  python3 - "$SCOUT_DIR/status.json" "$1" "$2" "${LOG:-}" <<'PY'
import json, os, sys
from datetime import datetime, timedelta, timezone
path, state, message, log = sys.argv[1:5]
now = datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")
try:
    data = json.load(open(path, encoding="utf-8"))
except (OSError, ValueError):
    data = {}
data.update(state=state, message=message, log=log)
data["started_at" if state == "running" else "finished_at"] = now
if state == "running":
    data.pop("finished_at", None)
if state == "ok":
    data["last_ok_at"] = now
json.dump(data, open(path + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
os.replace(path + ".tmp", path)
PY
}

if [[ "${1:-}" == "inner" ]]; then
  # tmux 창 안에서 실행되는 부분. 창의 환경은 tmux 서버 것이므로 필요한 값은 인자로 받는다.
  LOG="$2"; MODEL="$3"
  cd "$SCOUT_DIR"
  rm -f draft.json
  echo "[$(date '+%F %T')] Claude 대회 탐색 시작 (model=$MODEL) — 끝나면 이 창은 그대로 남습니다."
  set +e
  claude -p "$(cat "$SCOUT_DIR/prompt.txt")" --model "$MODEL" --permission-mode acceptEdits \
    --allowedTools WebSearch WebFetch --disallowedTools Bash Edit NotebookEdit 2>&1 | tee -a "$LOG"
  code=${PIPESTATUS[0]}
  set -e
  echo "$code" > "$SCOUT_DIR/.exit_code"
  echo "[$(date '+%F %T')] Claude 종료(code=$code)" | tee -a "$LOG"
  exit 0
fi

mkdir -p "$SCOUT_DIR/logs"
rm -f "$SCOUT_DIR/run-request" "$SCOUT_DIR/.exit_code"
LOG="$SCOUT_DIR/logs/$(TZ=Asia/Seoul date +%F_%H%M).log"
status running "Claude 가 tmux 세션 '$SESSION' 에서 대회를 찾는 중"

python3 - "$HERE/prompt.md" "$SCOUT_DIR/prompt.txt" <<'PY'
import json, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
src, dst = sys.argv[1:3]
lines = []
for f in sorted(Path("/srv/contests").glob("*/contest.json")):
    try:
        c = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        continue
    lines.append(f"  - {c.get('title', f.parent.name)} {c.get('url', '').split('?')[0]}")
now = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
text = Path(src).read_text(encoding="utf-8").replace("{{NOW}}", now).replace("{{MONTH}}", datetime.now(timezone(timedelta(hours=9))).strftime("%B %Y")).replace("{{EXISTING}}", "\n".join(lines) or "  - 없음")
Path(dst).write_text(text, encoding="utf-8")
PY

# 목록 화면이 JS 로 그려지는 사이트는 JSON 을 미리 받아 둔다(실패해도 계속, 결과는 로그에).
rm -rf "$SCOUT_DIR/sources"
python3 -I "$HERE/fetch_sources.py" "$SCOUT_DIR" >> "$LOG" 2>&1 || true
tmux kill-session -t "$SESSION" 2>/dev/null || true
tmux new-session -d -s "$SESSION" -x 200 -y 50 "bash '$HERE/run_scout.sh' inner '$LOG' '$MODEL'"
tmux set-option -t "$SESSION" remain-on-exit on >/dev/null

deadline=$(( $(date +%s) + TIMEOUT_MIN * 60 ))
while [[ ! -f "$SCOUT_DIR/.exit_code" ]]; do
  if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    status failed "tmux 세션이 Claude 종료 전에 사라졌습니다"; exit 1
  fi
  if (( $(date +%s) > deadline )); then
    tmux kill-session -t "$SESSION" 2>/dev/null || true
    status failed "${TIMEOUT_MIN}분 안에 끝나지 않아 중단했습니다"; exit 1
  fi
  sleep 20
done

code=$(cat "$SCOUT_DIR/.exit_code")
if [[ "$code" != "0" ]]; then
  status failed "Claude 가 오류로 끝났습니다(code=$code). 로그를 확인하세요"; exit 1
fi
if ! msg=$(python3 "$HERE/finalize.py" "$SCOUT_DIR" 2>&1); then
  echo "$msg" >> "$LOG"
  status failed "$msg"; exit 1
fi
echo "$msg" >> "$LOG"
status ok "$msg"
