#!/usr/bin/env bash
# 세션 자동 재개 타이머 설치(1회). 자동배포는 유닛 파일을 설치하지 않으므로 처음 한 번만 VM 에서 실행한다.
set -euo pipefail
cd "$(dirname "$0")"
sudo install -d -o quant -g quant -m 755 /opt/quant/data/session_resume
sudo install -m 644 quant-session-resume.service /etc/systemd/system/quant-session-resume.service
sudo install -m 644 quant-session-resume.timer /etc/systemd/system/quant-session-resume.timer
sudo systemctl daemon-reload
sudo systemctl enable --now quant-session-resume.timer
systemctl list-timers quant-session-resume.timer --no-pager
