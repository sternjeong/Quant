#!/usr/bin/env bash
# Oracle Cloud "Always Free" ARM VM(Ubuntu) 부트스트랩 스크립트.
# 로컬에서 손으로 하면 실수하기 쉬운 반복 작업(패키지 설치, venv, systemd 등록, 방화벽)만
# 자동화한다. Oracle Cloud 콘솔의 VCN Security List/NSG에서 80/8501 포트를 여는 것은 이
# 스크립트가 대신 할 수 없다 — deploy/DEPLOYMENT_ORACLE.md 4단계 참고.
#
# 사용법 (VM에 SSH 접속한 뒤, 리포를 이미 /opt/quant 에 clone 해둔 상태에서):
#   sudo bash deploy/setup_vm.sh
set -euo pipefail

APP_DIR="/opt/quant"
SERVICE_USER="quant"

if [ "$(id -u)" -ne 0 ]; then
  echo "root 권한으로 실행하세요 (sudo bash deploy/setup_vm.sh)" >&2
  exit 1
fi

if [ ! -d "$APP_DIR" ]; then
  echo "$APP_DIR 가 없습니다. 먼저 'git clone <repo> $APP_DIR' 로 리포를 받아두세요." >&2
  exit 1
fi

echo "[1/6] 시스템 패키지 설치"
apt-get update -y
apt-get install -y python3.12 python3.12-venv python3-pip git ufw nginx

echo "[2/6] 서비스 전용 사용자 생성 ($SERVICE_USER)"
id -u "$SERVICE_USER" &>/dev/null || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

echo "[3/6] 가상환경 + 의존성 설치"
sudo -u "$SERVICE_USER" python3.12 -m venv "$APP_DIR/.venv"
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [ ! -f "$APP_DIR/.env" ]; then
  echo "[!] $APP_DIR/.env 가 없습니다. .env.example을 참고해 직접 채운 뒤 다시 실행하세요." >&2
  echo "    (FRED_API_KEY, GEMINI_API_KEYS 등 — deploy/DEPLOYMENT_ORACLE.md 3단계 참고)" >&2
  exit 1
fi
chmod 600 "$APP_DIR/.env"
chown "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/.env"

echo "[4/6] data/ 디렉터리 준비 (SQLite 파일 + 캐시가 여기 저장됨)"
sudo -u "$SERVICE_USER" mkdir -p "$APP_DIR/data/cache"

echo "[5/6] systemd 서비스 등록"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" "$APP_DIR/.vm-health-state"
cp "$APP_DIR/deploy/quant-alert@.service" /etc/systemd/system/
cp "$APP_DIR/deploy/quant-streamlit.service" /etc/systemd/system/
cp "$APP_DIR/deploy/quant-scheduler.service" /etc/systemd/system/
cp "$APP_DIR/deploy/quant-vm-health.service" /etc/systemd/system/
cp "$APP_DIR/deploy/quant-vm-health.timer" /etc/systemd/system/
cp "$APP_DIR/deploy/quant-auto-deploy.service" /etc/systemd/system/
cp "$APP_DIR/deploy/quant-auto-deploy.timer" /etc/systemd/system/
cp "$APP_DIR/deploy/quant-hub.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now quant-streamlit.service
systemctl enable --now quant-scheduler.service
systemctl enable --now quant-vm-health.timer
systemctl enable --now quant-hub.service
# quant-auto-deploy.service는 oneshot이라 직접 enable하지 않고, 주기 실행을 맡는
# 타이머만 enable --now 한다 (타이머가 활성화되면 필요할 때 서비스를 기동한다).
systemctl enable --now quant-auto-deploy.timer
# 리서치 에이전트 B/C는 더 이상 VM 상주 systemd 타이머가 아니다 (DEPLOYMENT_ORACLE.md 10번
# 참고 — Codespace 세션 안에서 Claude Code가 대신 실행한다). deploy/research_agents/는
# 저장소에서 제거됐으므로 여기서 더는 참조하지 않는다.

echo "[5.5/6] nginx: 최상위 진입점을 관제 허브(hub/server.py)로 연결"
rm -f /etc/nginx/sites-enabled/default
cp "$APP_DIR/deploy/nginx-quant.conf" /etc/nginx/sites-available/quant-hub
ln -sf /etc/nginx/sites-available/quant-hub /etc/nginx/sites-enabled/quant-hub
nginx -t
systemctl enable --now nginx
systemctl reload nginx

echo "[6/6] 방화벽(OS 레벨)에서 80/8501 포트 허용"
ufw allow 22/tcp || true
ufw allow 80/tcp || true
ufw allow 8501/tcp || true
ufw --force enable || true

echo
echo "완료. 상태 확인:"
echo "  systemctl status quant-hub"
echo "  systemctl status quant-streamlit"
echo "  systemctl status quant-scheduler"
echo "  systemctl list-timers quant-vm-health.timer quant-auto-deploy.timer"
echo "  journalctl -u quant-streamlit -f     # 실시간 로그"
echo
echo "이제 http://<PUBLIC_IP>/ 로 접속하면 관제 허브가 뜨고, 슬롯을 누르면 각 앱/엔진으로 이동합니다"
echo "(퀀트 대시보드 슬롯은 http://<PUBLIC_IP>:8501/ 로 직접 이동)."
echo
echo "주의: Oracle Cloud 콘솔의 VCN Security List(또는 NSG)에서도 80/8501 TCP Ingress 규칙을"
echo "따로 추가해야 외부에서 접속됩니다 (OS 방화벽만 열어서는 부족함) — DEPLOYMENT_ORACLE.md 참고."
echo "code-server(브라우저 코드 스페이스)는 이 스크립트가 설치하지 않습니다 — 별도 안내는"
echo "DEPLOYMENT_ORACLE.md 14번, 남은 수동 조치는 PENDING_MANUAL_LOGIN_ACTIONS.md 5번 참고."
