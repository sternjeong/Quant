#!/usr/bin/env bash
# AI 대회 작업 공간 1회 설정 (관제 센터 'AI 대회' 섹션, core/contests.py, docs/AI_CONTESTS.md).
#
# 사용법: code-server 터미널(ubuntu 계정)에서   sudo bash /opt/quant/deploy/setup_contests.sh
#
# 하는 일(여러 번 돌려도 안전):
#   1. 그룹 contests 생성, ubuntu(code-server)·quant(허브) 계정을 그 그룹에 추가
#   2. /srv/contests 를 ubuntu:contests 2775(setgid)로 생성 — 허브가 만든 대회 폴더를 code-server 에서 편집·커밋 가능
#   3. 두 계정의 git 에 safe.directory 등록(다른 계정이 만든 저장소에서도 git 이 동작하게)
#   4. 두 계정이 gh 로그인돼 있으면 `gh auth setup-git` 로 git push 인증 연결
#   5. 새 그룹 권한이 적용되도록 quant-hub 와 code-server 재시작
# 비밀값을 만들거나 출력하지 않는다. gh 로그인 자체는 사람이 한다(안내만 출력).
set -euo pipefail

ROOT="${QUANT_CONTESTS_ROOT:-/srv/contests}"
GROUP="contests"
CODE_USER="ubuntu"
HUB_USER="quant"

if [ "$(id -u)" -ne 0 ]; then
  echo "root 권한이 필요합니다: sudo bash $0" >&2
  exit 1
fi

echo "[1/5] 그룹 ${GROUP}"
getent group "$GROUP" >/dev/null || groupadd "$GROUP"
usermod -aG "$GROUP" "$CODE_USER"
usermod -aG "$GROUP" "$HUB_USER"

echo "[2/5] ${ROOT}"
mkdir -p "$ROOT"
chown "$CODE_USER:$GROUP" "$ROOT"
chmod 2775 "$ROOT"
# 이미 있는 대회 폴더도 그룹 쓰기 가능하게 맞춘다
find "$ROOT" -mindepth 1 -maxdepth 1 -type d -exec chgrp -R "$GROUP" {} + -exec chmod -R g+rwX {} + 2>/dev/null || true

echo "[3/5] git safe.directory"
for u in "$CODE_USER" "$HUB_USER"; do
  if ! sudo -u "$u" git config --global --get-all safe.directory 2>/dev/null | grep -qx "${ROOT}/\*"; then
    sudo -u "$u" git config --global --add safe.directory "${ROOT}/*"
  fi
done

echo "[4/5] gh ↔ git push 인증"
for u in "$HUB_USER" "$CODE_USER"; do
  if sudo -u "$u" -H gh auth status >/dev/null 2>&1; then
    sudo -u "$u" -H gh auth setup-git && echo "  ${u}: 연결됨"
  else
    echo "  ${u}: gh 로그인 안 됨 — 필요하면 그 계정으로 'gh auth login' 후 이 스크립트를 다시 실행"
  fi
done

echo "[5/5] 서비스 재시작(새 그룹 권한 적용)"
echo "완료. 관제 센터 → 'AI 대회' 에서 새 대회를 만들 수 있습니다."
echo "code-server 에서 대회 저장소로 push 하려면 ${CODE_USER} 계정도 gh 로그인이 필요합니다(위 4번 결과 참고)."
echo "곧 code-server 가 재시작되어 이 터미널이 끊깁니다(정상). 새로고침하면 다시 접속됩니다."
systemctl restart quant-hub || true
sleep 2
systemctl restart "code-server@${CODE_USER}" || true
