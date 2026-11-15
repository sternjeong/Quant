#!/usr/bin/env bash
# 놀고 있는 AI 세션 점검 타이머 설치(1회). 자동배포는 유닛 파일을 설치하지 않으므로 처음 한 번만 VM 에서 실행한다.
set -euo pipefail
cd "$(dirname "$0")"
sudo install -d -o quant -g quant -m 755 /opt/quant/data/session_reaper
sudo install -m 644 quant-session-reaper.service /etc/systemd/system/quant-session-reaper.service
sudo install -m 644 quant-session-reaper.timer /etc/systemd/system/quant-session-reaper.timer
sudo systemctl daemon-reload
sudo systemctl enable --now quant-session-reaper.timer
systemctl list-timers quant-session-reaper.timer --no-pager
