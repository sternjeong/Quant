#!/usr/bin/env bash
# code-server(브라우저 코드 스페이스) 로그인 비밀번호를 사람이 외울 수 있는 것으로 바꾼다 (대화형).
#
# 자동 생성된 24자 랜덤 비밀번호는 외울 수 없어 매번 찾아 붙여넣어야 한다. 이 스크립트는 사용자가 직접
# 고른 비밀번호를 물어보고(화면에 표시 안 됨, 두 번 입력) 설정 파일에 넣은 뒤 code-server를 재시작한다.
# 비밀번호는 명령줄 인자로 넘기지 않으므로 `ps`나 셸 기록, 대화 로그에 남지 않는다 — 반드시 사람이 직접
# 터미널에서 실행한다(대화형 입력이 필요해서 ssh에 -t가 있어야 한다).
#
# 사용법 (VM에서 root로): sudo bash deploy/set_code_server_password.sh
#   원격에서 한 줄로:     ssh -t quant-vm 'sudo bash /opt/quant/deploy/set_code_server_password.sh'
#
# 규칙: 12자 이상, 영문/숫자/`.`/`_`/`-`만 (셸·YAML에서 안전하도록). 이 비밀번호 하나가 곧 VM 셸이라
# 4자리 숫자 같은 건 받지 않는다 — 단어 3~4개를 하이픈으로 이으면 길이도 되고 외우기도 쉽다(blue-moon-cat-42 형태).
#
# 새 비밀번호로 실제 로그인이 되는지 확인해서 안 되면 예전 설정으로 되돌린다. 설정 파일의 소유자/권한은 유지한다.
#
# 테스트용 환경변수: CODE_SERVER_CONFIG(설정 파일 경로), CODE_SERVER_SERVICE(비우면 재시작/로그인 확인 생략).
set -euo pipefail

CONFIG="${CODE_SERVER_CONFIG:-/home/ubuntu/.config/code-server/config.yaml}"
SERVICE="${CODE_SERVER_SERVICE-code-server@ubuntu.service}"
LOGIN_URL="${CODE_SERVER_LOGIN_URL:-http://127.0.0.1:8080/login}"
MIN_LEN=12

if [ -z "${CODE_SERVER_CONFIG:-}" ] && [ "$(id -u)" -ne 0 ]; then
  echo "root 권한이 필요합니다: sudo bash $0" >&2
  exit 1
fi
if [ ! -f "$CONFIG" ]; then
  echo "설정 파일이 없습니다: $CONFIG" >&2
  exit 1
fi
if ! grep -q '^password:' "$CONFIG"; then
  echo "설정 파일에 'password:' 항목이 없습니다(다른 인증 방식일 수 있음) — 직접 확인이 필요합니다." >&2
  exit 1
fi
if grep -q '^hashed-password:' "$CONFIG"; then
  echo "'hashed-password:'가 설정돼 있어 이 스크립트로는 바꿀 수 없습니다(그 값이 password보다 우선함)." >&2
  exit 1
fi

read -rsp "새 비밀번호 (${MIN_LEN}자 이상, 영문/숫자/./_/-): " pw1 || { echo; echo "입력을 받지 못했습니다 — ssh에 -t를 붙여 대화형으로 실행하세요." >&2; exit 1; }
echo
read -rsp "한 번 더: " pw2 || { echo; echo "입력을 받지 못했습니다." >&2; exit 1; }
echo

if [ "$pw1" != "$pw2" ]; then
  echo "두 입력이 다릅니다. 아무것도 바꾸지 않았습니다." >&2
  exit 1
fi
if [ "${#pw1}" -lt "$MIN_LEN" ]; then
  echo "너무 짧습니다(${#pw1}자). ${MIN_LEN}자 이상이어야 합니다 — 단어 3~4개를 하이픈으로 이어보세요. 아무것도 바꾸지 않았습니다." >&2
  exit 1
fi
if [[ ! "$pw1" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "영문/숫자/./_/- 만 쓸 수 있습니다(공백·한글·따옴표 등 불가). 아무것도 바꾸지 않았습니다." >&2
  exit 1
fi

backup="$(mktemp "${CONFIG}.bak.XXXXXX")"
cp -p "$CONFIG" "$backup"
tmp="$(mktemp "${CONFIG}.new.XXXXXX")"
cleanup() { rm -f "$tmp"; }
trap cleanup EXIT

# 비밀번호는 환경변수로만 awk에 전달한다(명령줄에 안 남음). 값은 홑따옴표로 감싸 숫자만 있어도 문자열로 읽히게 한다.
PW="$pw1" awk 'BEGIN { pw = ENVIRON["PW"] } /^password:/ { print "password: \x27" pw "\x27"; next } { print }' "$CONFIG" > "$tmp"
chown --reference="$CONFIG" "$tmp"
chmod --reference="$CONFIG" "$tmp"
mv "$tmp" "$CONFIG"

rollback() {
  echo "되돌립니다 — 예전 설정으로 복구." >&2
  cp -p "$backup" "$CONFIG"
  if [ -n "$SERVICE" ]; then systemctl restart "$SERVICE" || true; fi
  rm -f "$backup"
}

if [ -z "$SERVICE" ]; then
  rm -f "$backup"
  echo "설정 파일만 바꿨습니다(재시작 생략)."
  exit 0
fi

echo "code-server 재시작 중..."
if ! systemctl restart "$SERVICE"; then rollback; exit 1; fi

up=0
for _ in $(seq 1 20); do
  if curl -s -o /dev/null -m 3 "${LOGIN_URL%/login}/healthz"; then up=1; break; fi
  sleep 1
done
if [ "$up" -ne 1 ]; then
  echo "code-server가 다시 올라오지 않았습니다." >&2
  rollback
  exit 1
fi

# 새 비밀번호로 로그인이 되는지 확인: 성공하면 302(리다이렉트), 틀리면 200(로그인 화면 재표시).
# 본문은 stdin으로 넘겨 비밀번호가 명령줄에 안 남게 한다.
code="$(printf 'password=%s' "$pw1" | curl -s -o /dev/null -m 10 -w '%{http_code}' -d @- "$LOGIN_URL" || true)"
case "$code" in
  302|303)
    rm -f "$backup"
    echo "완료 — 새 비밀번호로 로그인 확인됨."
    ;;
  200)
    echo "새 비밀번호로 로그인이 되지 않았습니다(HTTP 200)." >&2
    rollback
    exit 1
    ;;
  *)
    rm -f "$backup"
    echo "완료 — 다만 로그인 확인 응답이 예상 밖(HTTP ${code:-없음})이라 자동 확인은 못 했습니다. 브라우저로 직접 로그인해 보세요."
    ;;
esac
echo "이제 https://code.<도메인>/ 에서 새 비밀번호를 쓰세요. 브라우저의 '비밀번호 저장'을 누르면 다음부터는 안 쳐도 됩니다."
