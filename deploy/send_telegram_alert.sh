#!/usr/bin/env bash
# Oracle VM에서 도는 운영 스크립트(서비스 실패 알림, 자동 배포, 리소스 헬스체크 등)가 공통으로 쓰는
# 텔레그램 발송 헬퍼. deploy/codex_telegram/runner.py가 쓰는 것과 같은 봇/채팅으로 보낸다 — 새 봇을
# 따로 만들지 않고 telegram.env 하나만 공유한다.
#
# 사용법: deploy/send_telegram_alert.sh "메시지 본문"
# 환경변수로 env 파일 경로를 바꿀 수 있다: TELEGRAM_ALERT_ENV_FILE=/other/path.env
set -uo pipefail

ENV_FILE="${TELEGRAM_ALERT_ENV_FILE:-/opt/quant/.codex-telegram-runtime/telegram.env}"

if [ $# -lt 1 ] || [ -z "$1" ]; then
  echo "사용법: $0 \"메시지 본문\"" >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "telegram env 파일을 찾을 수 없음: $ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
  echo "TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 비어 있음: $ENV_FILE" >&2
  exit 1
fi

curl -sS --max-time 10 -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
  --data-urlencode "text=$1" \
  -o /dev/null
