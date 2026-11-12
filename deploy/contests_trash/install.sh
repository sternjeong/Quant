#!/usr/bin/env bash
# AI 대회 휴지통 비우기 타이머 설치(1회). 자동배포는 유닛 파일을 설치하지 않으므로 처음 한 번만 VM 에서 실행한다.
set -euo pipefail
cd "$(dirname "$0")"
sudo install -d -o quant -g contests -m 2775 /srv/contests/.trash
sudo install -m 644 quant-contests-trash.service /etc/systemd/system/quant-contests-trash.service
sudo install -m 644 quant-contests-trash.timer /etc/systemd/system/quant-contests-trash.timer
sudo systemctl daemon-reload
sudo systemctl enable --now quant-contests-trash.timer
systemctl list-timers quant-contests-trash.timer --no-pager
