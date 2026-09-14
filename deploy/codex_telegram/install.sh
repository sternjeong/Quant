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
sudo install -m 644 codex-telegram.service /etc/systemd/system/codex-telegram.service
sudo systemctl daemon-reload
sudo systemctl enable --now codex-telegram.service
sudo systemctl is-active codex-telegram.service
