#!/usr/bin/env bash
# VM 백업 시스템 설치 (root로, 여러 번 돌려도 안전).
#   sudo bash /opt/quant/deploy/setup_backup.sh
#
# 하는 일: 백업 폴더(/opt/quant-backup, quant 소유·그룹 접근 불가) 생성 → 전용 SSH 배포 키 생성(개인 키는 VM 밖으로
# 안 나감) → GitHub 호스트 키 고정(known_hosts) → quant 계정을 비밀 암호화 백업 대상 파일을 읽어야 하는 그룹(www-data,
# ubuntu)에 추가 → systemd 서비스/타이머 설치·활성화 → **공개 키**와 남은 수동 단계 출력.
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

echo "[1/5] 백업 폴더"
mkdir -p "$BACKUP_DIR/ssh"
chown -R "$SERVICE_USER:$SERVICE_USER" "$BACKUP_DIR"
chmod 750 "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR/ssh"

echo "[2/5] 전용 SSH 배포 키 (이 백업 저장소 하나에만 쓰는 키)"
if [ ! -f "$BACKUP_DIR/ssh/id_ed25519" ]; then
  sudo -u "$SERVICE_USER" ssh-keygen -q -t ed25519 -N "" -C "quant-vm-backup" -f "$BACKUP_DIR/ssh/id_ed25519"
  echo "  새 키를 만들었습니다."
else
  echo "  이미 있음 — 그대로 사용"
fi

echo "[3/5] GitHub 호스트 키 고정"
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

echo "[4/5] 비밀 암호화 백업이 읽을 파일들에 quant 계정 접근 권한 부여"
# nginx 로그인 파일(/etc/nginx/.htpasswd-quant)은 root:www-data 640으로 만들어진다(DEPLOYMENT_ORACLE.md 14번의
# 비밀번호 설정 명령이 항상 이 소유권으로 만듦) — www-data 그룹에 넣어두면 파일이 나중에 새로 생기거나
# 비밀번호가 바뀌어도(같은 명령이 매번 같은 소유권을 쓰므로) 계속 읽을 수 있다.
usermod -aG www-data "$SERVICE_USER"
# code-server 설정(/home/ubuntu/.config/code-server/config.yaml)은 ubuntu 소유라 그 계정의 홈 디렉터리(권한 750)를
# 지나가려면 ubuntu 그룹이 필요하다. 파일 자체의 읽기 권한(640)은 deploy/set_code_server_password.sh가 비밀번호를
# 바꿀 때마다 강제한다 — 그 스크립트를 아직 한 번도 안 돌렸다면 여기서 존재하는 파일만 한 번 맞춰둔다(비치명적).
usermod -aG ubuntu "$SERVICE_USER"
code_server_config="/home/ubuntu/.config/code-server/config.yaml"
if [ -f "$code_server_config" ]; then
  chmod 640 "$code_server_config" || true
fi
echo "  완료 (재로그인 없이도 systemd가 새로 띄우는 백업 서비스부터 바로 적용됨)"

echo "[5/5] systemd 서비스/타이머"
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
