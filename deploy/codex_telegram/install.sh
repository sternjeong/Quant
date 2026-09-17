#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ "$(cat /proc/1/comm)" != systemd ]; then
  echo 'Cannot install: PID 1 is not systemd. Run on the Ubuntu host, not this container.' >&2
  exit 1
fi
test -f config.json || sudo install -o quant -g quant -m 600 config.example.json config.json
sudo chmod 600 config.json
sudo -u quant npm install --prefix /opt/quant/.codex-telegram-runtime @openai/codex@0.154.0
# codex-telegram.service의 [Unit]에는 OnFailure=quant-alert@%n.service가 걸려 있다.
# setup_vm.sh를 거치지 않고 이 스크립트만으로 단독 설치하는 경우에도 실패 알림이 동작하도록
# 알림 템플릿 유닛도 같이 설치해둔다 (템플릿이라 enable --now는 하지 않음 — 실패 시 systemd가
# 알아서 인스턴스화한다).
sudo install -m 644 ../quant-alert@.service /etc/systemd/system/quant-alert@.service
sudo install -m 644 codex-telegram.service /etc/systemd/system/codex-telegram.service
sudo systemctl daemon-reload
sudo systemctl enable --now codex-telegram.service
sudo systemctl is-active codex-telegram.service
