#!/usr/bin/env bash
# VM 백업 시스템 설치 (root로, 여러 번 돌려도 안전).
#   sudo bash /opt/quant/deploy/setup_backup.sh
#
# 하는 일: 백업 폴더(/opt/quant-backup, quant 소유·그룹 접근 불가) 생성 → 전용 SSH 배포 키 생성(개인 키는 VM 밖으로
# 안 나감) → GitHub 호스트 키 고정(known_hosts) → systemd 서비스/타이머 설치·활성화 → **공개 키**와 남은 수동 단계 출력.
# 비공개 저장소가 아직 없어도 동작한다: 그때는 VM 안의 로컬 버전 저장소에만 쌓이고(status.json의 offsite_configured=false),
# 저장소를 만들고 배포 키를 등록한 뒤 remote 파일에 URL만 넣으면 그다음 실행부터 밖으로도 올라간다.
set -euo pipefail

APP_DIR="/opt/quant"
BACKUP_DIR="/opt/quant-backup"
SERVICE_USER="quant"

if [ "$(id -u)" -ne 0 ]; then
  echo "root 권한이 필요합니다: sudo bash $0" >&2
  exit 1
fi

echo "[1/4] 백업 폴더"
mkdir -p "$BACKUP_DIR/ssh"
chown -R "$SERVICE_USER:$SERVICE_USER" "$BACKUP_DIR"
chmod 750 "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR/ssh"

echo "[2/4] 전용 SSH 배포 키 (이 백업 저장소 하나에만 쓰는 키)"
if [ ! -f "$BACKUP_DIR/ssh/id_ed25519" ]; then
  sudo -u "$SERVICE_USER" ssh-keygen -q -t ed25519 -N "" -C "quant-vm-backup" -f "$BACKUP_DIR/ssh/id_ed25519"
  echo "  새 키를 만들었습니다."
else
  echo "  이미 있음 — 그대로 사용"
fi

echo "[3/4] GitHub 호스트 키 고정"
PINNED="$APP_DIR/.codex-telegram-runtime/ssh/github_known_hosts"
if [ -f "$PINNED" ]; then
  # 텔레그램 러너 배포 때 이미 검증해 고정해둔 파일을 그대로 재사용한다.
  install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 644 "$PINNED" "$BACKUP_DIR/ssh/known_hosts"
  echo "  기존 고정 파일 사용"
elif [ ! -s "$BACKUP_DIR/ssh/known_hosts" ]; then
  ssh-keyscan -t ed25519,rsa github.com 2>/dev/null > "$BACKUP_DIR/ssh/known_hosts"
  chown "$SERVICE_USER:$SERVICE_USER" "$BACKUP_DIR/ssh/known_hosts"
  echo "  ssh-keyscan으로 새로 받음 — GitHub 문서의 공개 지문과 대조해 확인하는 것을 권장"
fi

echo "[4/4] systemd 서비스/타이머"
cp "$APP_DIR/deploy/quant-backup.service" /etc/systemd/system/
cp "$APP_DIR/deploy/quant-backup.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now quant-backup.timer

echo
echo "완료. 다음 백업: $(systemctl list-timers quant-backup.timer --no-legend | awk '{print $1, $2, $3}')"
echo
if [ -s "$BACKUP_DIR/remote" ]; then
  echo "비공개 원격이 설정돼 있습니다: $(cat "$BACKUP_DIR/remote")"
else
  echo "── 남은 수동 단계 (비공개 저장소로 밖에 백업하려면) ─────────────────────────────"
  echo " 1. GitHub에서 **비공개(Private)** 저장소를 만든다 (예: quant-vm-backup). Quant 저장소는 공개라 여기에 올리면 안 됨."
  echo " 2. 그 저장소 Settings → Deploy keys → Add deploy key → 아래 공개 키를 붙여넣고 'Allow write access'를 체크."
  echo " 3. VM에서:  echo 'git@github.com:<계정>/<저장소>.git' | sudo -u $SERVICE_USER tee $BACKUP_DIR/remote"
  echo " 4. 확인:    sudo -u $SERVICE_USER python3 $APP_DIR/deploy/backup_vm.py"
  echo
  echo "공개 키(등록용 — 비밀 아님):"
  cat "$BACKUP_DIR/ssh/id_ed25519.pub"
fi
