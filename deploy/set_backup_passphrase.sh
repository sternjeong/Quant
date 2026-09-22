#!/usr/bin/env bash
# 암호화된 비밀 백업(deploy/backup_vm.py의 backup_secrets())에서 쓸 passphrase를 사람이 직접 정한다 (대화형).
#
# 이 스크립트가 만드는 파일(BACKUP_DIR/secrets_passphrase)은 백업 대상 디렉터리(APP_DIR) 밖에 있어서
# 절대 백업에 함께 수집되지 않고, 백업 저장소(비공개 원격 포함)에도 올라가지 않는다 — 즉 "백업 저장소가
# 뚫려도 이 파일 없이는 nginx 로그인·code-server 비밀번호·.env·텔레그램 토큰·Claude/Codex 로그인 세션을
# 못 연다"는 것까지는 지켜준다. 다만 "VM 디스크가 통째로 사라지는 경우"까지 막으려면, 같은 passphrase를
# 사람이 따로(비밀번호 관리자 등에) 보관해야 한다 — 이 파일 하나만 믿으면 디스크와 함께 passphrase도
# 사라진다. 비밀번호는 명령줄 인자로 넘기지 않으므로 `ps`나 셸 기록, 대화 로그에 남지 않는다 — 반드시
# 사람이 직접 터미널에서 실행한다(대화형 입력이 필요해서 ssh에 -t가 있어야 한다).
#
# 사용법 (VM에서 root로): sudo bash deploy/set_backup_passphrase.sh
#   원격에서 한 줄로:     ssh -t quant-vm 'sudo bash /opt/quant/deploy/set_backup_passphrase.sh'
#
# 규칙: 20자 이상. 이 밖에는 제한이 없다 — 값이 셸 명령에 끼워 넣어지지 않고 파일로만 저장되므로 공백·
# 특수문자도 안전하다. 영어 단어 4~5개를 띄어 쓴 문장 형태가 외우기 쉽고 충분히 길다.
#
# 저장 뒤 방금 만든 passphrase로 실제 암복호화 왕복(원문 == 복호화 결과)까지 확인하고, 실패하면 아무것도
# 남기지 않는다(예전 파일이 있었으면 그대로 둠).
#
# 다음 백업 실행부터 자동으로 비밀 5종을 암호화해 포함한다 — 바로 확인하려면:
#   ssh quant-vm 'sudo -u quant python3 /opt/quant/deploy/backup_vm.py'
#
# 테스트용 환경변수: QUANT_BACKUP_DIR(기본값 대신 사용할 디렉터리 — 지정하면 root 요구·소유자 변경을 건너뜀).
set -euo pipefail

BACKUP_DIR="${QUANT_BACKUP_DIR:-/opt/quant-backup}"
OWNER="${QUANT_BACKUP_OWNER:-quant}"
TARGET="$BACKUP_DIR/secrets_passphrase"
MIN_LEN=20

if [ -z "${QUANT_BACKUP_DIR:-}" ] && [ "$(id -u)" -ne 0 ]; then
  echo "root 권한이 필요합니다: sudo bash $0" >&2
  exit 1
fi
if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl이 없습니다 — 이 VM에는 있어야 정상입니다." >&2
  exit 1
fi

read -rsp "새 passphrase (${MIN_LEN}자 이상, 공백/문장 형태도 가능): " pw1 || { echo; echo "입력을 받지 못했습니다 — ssh에 -t를 붙여 대화형으로 실행하세요." >&2; exit 1; }
echo
read -rsp "한 번 더: " pw2 || { echo; echo "입력을 받지 못했습니다." >&2; exit 1; }
echo

if [ "$pw1" != "$pw2" ]; then
  echo "두 입력이 다릅니다. 아무것도 바꾸지 않았습니다." >&2
  exit 1
fi
if [ "${#pw1}" -lt "$MIN_LEN" ]; then
  echo "너무 짧습니다(${#pw1}자). ${MIN_LEN}자 이상이어야 합니다 — 단어 4~5개를 띄어 써보세요. 아무것도 바꾸지 않았습니다." >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
tmp="$(mktemp "$BACKUP_DIR/secrets_passphrase.new.XXXXXX")"
cleanup() { rm -f "$tmp"; }
trap cleanup EXIT
printf '%s' "$pw1" > "$tmp"
chmod 600 "$tmp"
if [ "$(id -u)" -eq 0 ]; then chown "$OWNER:$OWNER" "$tmp" 2>/dev/null || true; fi

echo "확인 중(방금 만든 passphrase로 실제 암호화→복호화 왕복)..."
sample="quant-backup-passphrase-self-test"
encrypted="$(printf '%s' "$sample" | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass file:"$tmp" 2>/dev/null | base64 -w0)" || {
  echo "암호화 자체가 실패했습니다(openssl 문제로 보임). 아무것도 바꾸지 않았습니다." >&2
  exit 1
}
decrypted="$(printf '%s' "$encrypted" | base64 -d | openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass file:"$tmp" 2>/dev/null)" || {
  echo "복호화 확인이 실패했습니다. 아무것도 바꾸지 않았습니다." >&2
  exit 1
}
if [ "$decrypted" != "$sample" ]; then
  echo "왕복 확인 결과가 일치하지 않습니다. 아무것도 바꾸지 않았습니다." >&2
  exit 1
fi

mv "$tmp" "$TARGET"
trap - EXIT
echo "완료 — passphrase가 저장됐고 암복호화 왕복 확인도 통과했습니다."
echo "다음 백업부터 nginx 로그인·code-server 비밀번호·.env·텔레그램 토큰·Claude/Codex 로그인 세션이 암호화돼 함께 백업됩니다."
echo "지금 바로 확인하려면: ssh quant-vm 'sudo -u quant python3 /opt/quant/deploy/backup_vm.py'"
echo
echo "중요: 이 passphrase는 VM에만 저장돼 있습니다. VM 디스크가 통째로 사라지는 경우까지 대비하려면,"
echo "방금 입력한 것과 같은 값을 본인이 비밀번호 관리자 등에 따로 적어두세요 — 저는 이 값을 모르고 알 수도 없습니다."
