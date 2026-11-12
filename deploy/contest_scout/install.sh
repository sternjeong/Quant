#!/usr/bin/env bash
# 주간 대회 탐색 타이머 설치(1회). 자동배포는 유닛 파일을 설치하지 않으므로 처음 한 번만 VM 에서 실행한다.
set -euo pipefail
cd "$(dirname "$0")"
sudo install -d -o ubuntu -g contests -m 2775 /srv/contests/.scout
for unit in quant-contest-scout.service quant-contest-scout.timer quant-contest-scout.path; do
  sudo install -m 644 "$unit" "/etc/systemd/system/$unit"
done
sudo systemctl daemon-reload
sudo systemctl enable --now quant-contest-scout.timer quant-contest-scout.path
systemctl list-timers quant-contest-scout.timer --no-pager
