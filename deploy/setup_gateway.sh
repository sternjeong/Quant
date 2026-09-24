#!/usr/bin/env bash
# 하나의 도메인 아래에 관제 허브와 하위 앱들을 HTTPS로 모아 공개하는 게이트웨이(nginx) 설정.
#
#   https://<도메인>/         → 관제 허브        (127.0.0.1:8000)  [로그인 폼 → 쿠키; 검증은 htpasswd]
#   https://code.<도메인>/    → code-server      (127.0.0.1:8080)  [code-server 자체 비밀번호]
#   https://app.<도메인>/     → Streamlit 대시보드 (127.0.0.1:8501)  [허브와 같은 로그인 쿠키]
#   그 밖의 이름/IP로 오는 HTTPS 요청은 핸드셰이크를 거절하고, http://IP 는 위 도메인으로 리다이렉트한다.
#
# 사용법 (VM에서 root로): sudo bash deploy/setup_gateway.sh <기본 도메인> [인증서 알림 이메일]
#   예) sudo bash deploy/setup_gateway.sh hessejeong.duckdns.org
#
# 돌리기 전에 필요한 것:
#   1. DuckDNS 등에서 <도메인>이 이 VM의 공인 IP를 가리킴 (DuckDNS는 code.<도메인>, app.<도메인> 같은
#      하위 이름도 자동으로 같은 IP로 풀어준다 — 따로 등록할 필요 없음)
#   2. Oracle VCN Security List의 TCP 443 Ingress (80도 필요, 이미 열려 있음)
#   3. 허브/앱 로그인용 비밀번호 파일 /etc/nginx/.htpasswd-quant — 비밀번호를 대화나 명령줄에 남기지
#      않도록 사람이 직접 대화형으로 만든다 (deploy/DEPLOYMENT_ORACLE.md 14번의 명령 참고).
#      이 파일이 없으면 스크립트는 허브/앱을 로그인 없이 공개하지 않고 여기서 멈춘다.
#
# 하는 일: DNS 확인 → certbot 설치 → 세 이름을 한 장의 Let's Encrypt 인증서로 발급(자동 갱신 포함) →
#          nginx 게이트웨이 사이트 설치 → 방화벽 443 허용(iptables 즉시 + ufw 재부팅 후 유지) → 확인.
#   (이 VM의 Oracle 우분투 이미지는 iptables INPUT의 REJECT가 ufw 체인보다 앞이라 ufw allow만으로는 지금
#    당장 안 열리고, iptables-persistent가 없어 iptables 규칙만으로는 재부팅 때 사라진다 —
#    DEPLOYMENT_ORACLE.md 14번. 그래서 둘 다 넣는다.)
#
# 여러 번 돌려도 안전하다. nginx 단계에서 실패하면 건드린 사이트 파일을 직전 상태로 되돌리고 멈춘다.
# 하위 앱(127.0.0.1:8080/8501/8000) 자체는 건드리지 않는다 — 계속 로컬 전용이다.
set -euo pipefail

BASE="${1:-}"
EMAIL="${2:-}"
CODE_HOST="code.${BASE}"
APP_HOST="app.${BASE}"
WEBROOT="/var/www/html"
HTPASSWD_FILE="/etc/nginx/.htpasswd-quant"
GATEWAY_SITE="quant-gateway"
SITES_AVAILABLE="/etc/nginx/sites-available"
SITES_ENABLED="/etc/nginx/sites-enabled"
# 이 스크립트가 만들거나 바꾸거나 끄는 사이트 (실패하면 전부 되돌린다)
TOUCHED_SITES=("$GATEWAY_SITE" "code-server" "quant-hub")

if [ "$(id -u)" -ne 0 ]; then
  echo "root 권한이 필요합니다: sudo bash $0 <도메인> [이메일]" >&2
  exit 1
fi
if [[ ! "$BASE" =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$ ]]; then
  echo "도메인 형식이 올바르지 않습니다: '${BASE}'  (예: hessejeong.duckdns.org)" >&2
  exit 1
fi
if [ ! -s "$HTPASSWD_FILE" ]; then
  echo "${HTPASSWD_FILE} 이(가) 없거나 비어 있습니다." >&2
  echo "허브/앱을 로그인 없이 공개하지 않기 위해 여기서 멈춥니다 — 먼저 로그인 비밀번호를 만드세요." >&2
  echo "(명령은 deploy/DEPLOYMENT_ORACLE.md 14번 참고)" >&2
  exit 1
fi

echo "[1/7] DNS 확인: ${BASE}, ${CODE_HOST}, ${APP_HOST} → 이 VM의 공인 IP"
server_ip="$(curl -fsS -m 10 https://api.ipify.org || true)"
if [ -z "$server_ip" ]; then
  echo "이 VM의 공인 IP를 확인하지 못했습니다. 잠시 뒤 다시 시도하세요." >&2
  exit 1
fi
for host in "$BASE" "$CODE_HOST" "$APP_HOST"; do
  dns_ip="$(getent ahostsv4 "$host" | awk 'NR==1 {print $1}' || true)"
  if [ "$dns_ip" != "$server_ip" ]; then
    echo "${host} 은(는) ${dns_ip:-조회 실패} 를 가리키는데 이 VM의 공인 IP는 ${server_ip} 입니다." >&2
    echo "DNS를 고친 뒤 다시 실행하세요(인증서 발급 한도를 아끼려고 여기서 멈춥니다)." >&2
    exit 1
  fi
done
echo "  OK (전부 ${server_ip})"

echo "[2/7] 사전 준비 (certbot, 현재 nginx 사이트 백업)"
if ! command -v certbot >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y certbot
fi
mkdir -p "$WEBROOT"

BACKUP_DIR="$(mktemp -d)"
for site in "${TOUCHED_SITES[@]}"; do
  if [ -f "${SITES_AVAILABLE}/${site}" ]; then cp -p "${SITES_AVAILABLE}/${site}" "${BACKUP_DIR}/${site}.available"; fi
  if [ -e "${SITES_ENABLED}/${site}" ] || [ -L "${SITES_ENABLED}/${site}" ]; then : > "${BACKUP_DIR}/${site}.enabled"; fi
done

rollback() {
  echo "실패 — nginx 사이트를 직전 상태로 되돌립니다." >&2
  for site in "${TOUCHED_SITES[@]}"; do
    if [ -f "${BACKUP_DIR}/${site}.available" ]; then
      cp -p "${BACKUP_DIR}/${site}.available" "${SITES_AVAILABLE}/${site}"
    else
      rm -f "${SITES_AVAILABLE}/${site}"
    fi
    if [ -f "${BACKUP_DIR}/${site}.enabled" ]; then
      ln -sf "${SITES_AVAILABLE}/${site}" "${SITES_ENABLED}/${site}"
    else
      rm -f "${SITES_ENABLED}/${site}"
    fi
  done
  nginx -t >/dev/null 2>&1 && systemctl reload nginx || true
}

# 예전 단독 code-server 사이트가 있으면 같은 도메인을 가지므로 게이트웨이로 대체한다.
disable_old_code_server_site() { rm -f "${SITES_ENABLED}/code-server"; }

echo "[3/7] 인증서 발급용 임시 사이트 (80번: 인증 경로만 열고 나머지는 https로 리다이렉트)"
cat > "${SITES_AVAILABLE}/${GATEWAY_SITE}" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${BASE} ${CODE_HOST} ${APP_HOST};

    location /.well-known/acme-challenge/ { root ${WEBROOT}; }
    location / { return 301 https://\$host\$request_uri; }
}
EOF
disable_old_code_server_site
ln -sf "${SITES_AVAILABLE}/${GATEWAY_SITE}" "${SITES_ENABLED}/${GATEWAY_SITE}"
if ! nginx -t; then rollback; exit 1; fi
systemctl reload nginx

echo "[4/7] Let's Encrypt 인증서 (세 이름을 한 인증서에, 자동 갱신 포함)"
certbot_args=(certonly --webroot -w "$WEBROOT" --cert-name "$BASE" --expand
              -d "$BASE" -d "$CODE_HOST" -d "$APP_HOST"
              --non-interactive --agree-tos --deploy-hook "systemctl reload nginx")
if [ -n "$EMAIL" ]; then
  certbot_args+=(--email "$EMAIL")
else
  certbot_args+=(--register-unsafely-without-email)
fi
if ! certbot "${certbot_args[@]}"; then rollback; exit 1; fi

echo "[5/7] 최종 게이트웨이 사이트"
# 로그인 폼(hub /login)이 성공하면 브라우저에 이 토큰 쿠키를 심는다. 토큰은 사이트 파일(누구나 읽음)이 아니라
# root:www-data 640 파일에 두며, 이미 있으면 재사용한다(다시 만들면 모든 기기가 로그아웃된다).
SESSION_CONF="/etc/nginx/quant-session.conf"
if [ ! -s "$SESSION_CONF" ]; then
  umask 027
  printf 'map "" $qt_token { default "%s"; }\n' "$(openssl rand -hex 32)" > "$SESSION_CONF"
  chown root:www-data "$SESSION_CONF"
  chmod 640 "$SESSION_CONF"
fi
COOKIE_ATTRS="Domain=${BASE}; Path=/; HttpOnly; Secure; SameSite=Lax"
cat > "${SITES_AVAILABLE}/${GATEWAY_SITE}" <<EOF
include ${SESSION_CONF};

map \$http_upgrade \$gateway_connection_upgrade {
    default upgrade;
    ''      close;
}

# 등록되지 않은 이름/IP로 온 HTTPS는 인증서 정보도 주지 않고 거절한다.
server {
    listen 443 ssl http2 default_server;
    listen [::]:443 ssl http2 default_server;
    server_name _;
    ssl_reject_handshake on;
}

server {
    listen 80;
    listen [::]:80;
    server_name ${BASE} ${CODE_HOST} ${APP_HOST};

    location /.well-known/acme-challenge/ { root ${WEBROOT}; }
    location / { return 301 https://\$host\$request_uri; }
}

# 관제 허브
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${BASE};

    ssl_certificate     /etc/letsencrypt/live/${BASE}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${BASE}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:gateway_ssl:10m;

    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy no-referrer always;

    # 로그인 폼(공개). 브라우저 기본 팝업 대신 이 페이지에서 아이디/비밀번호를 받는다.
    location = /login {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$http_host;
        proxy_set_header Authorization "";
        add_header X-Content-Type-Options nosniff always;
        add_header Referrer-Policy no-referrer always;
        add_header Cache-Control "no-store" always;
    }

    # 폼이 Authorization 헤더로 호출한다. 자격 증명은 여전히 htpasswd 로 검증하고, 성공하면 세션 쿠키를 준다.
    # (401 은 WWW-Authenticate 없이 내려보내 브라우저 팝업이 뜨지 않게 한다.)
    location = /_login {
        auth_basic "Quant control tower";
        auth_basic_user_file ${HTPASSWD_FILE};
        error_page 401 = @login_denied;
        proxy_pass http://127.0.0.1:8000/healthz;
        proxy_set_header Authorization "";
        add_header Set-Cookie "qt_session=\$qt_token; ${COOKIE_ATTRS}; Max-Age=2592000" always;
        add_header Cache-Control "no-store" always;
    }
    location @login_denied {
        default_type text/plain;
        return 401 "denied";
    }
    location = /_logout {
        proxy_pass http://127.0.0.1:8000/healthz;
        proxy_set_header Authorization "";
        add_header Set-Cookie "qt_session=; ${COOKIE_ATTRS}; Max-Age=0" always;
        add_header Cache-Control "no-store" always;
    }

    location / {
        if (\$cookie_qt_session != \$qt_token) {
            return 302 https://${BASE}/login?next=\$scheme://\$host\$request_uri;
        }
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Authorization "";
    }
}

# 브라우저 코드 스페이스 (code-server 자체 로그인 사용)
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${CODE_HOST};

    ssl_certificate     /etc/letsencrypt/live/${BASE}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${BASE}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:gateway_ssl:10m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$gateway_connection_upgrade;
        proxy_set_header Accept-Encoding gzip;
        proxy_read_timeout 86400;
    }
}

# Streamlit 퀀트 대시보드
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${APP_HOST};

    ssl_certificate     /etc/letsencrypt/live/${BASE}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${BASE}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:gateway_ssl:10m;

    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy no-referrer always;

    # 로그인은 허브(https://${BASE}/login)에서 하고, 같은 도메인 쿠키를 공유한다.
    location / {
        if (\$cookie_qt_session != \$qt_token) {
            return 302 https://${BASE}/login?next=\$scheme://\$host\$request_uri;
        }
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$gateway_connection_upgrade;
        proxy_set_header Authorization "";
        proxy_read_timeout 86400;
    }
}
EOF

# IP로 들어오는 평문 HTTP(기본 서버)는 더 이상 로그인 없는 허브를 보여주지 않고 도메인으로 보낸다.
cat > "${SITES_AVAILABLE}/quant-hub" <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    location / { return 301 https://${BASE}\$request_uri; }
}
EOF
ln -sf "${SITES_AVAILABLE}/quant-hub" "${SITES_ENABLED}/quant-hub"
if ! nginx -t; then rollback; exit 1; fi
systemctl reload nginx

echo "[6/7] 방화벽: 443 허용 (지금 즉시 + 재부팅 후에도)"
# 지금 즉시: iptables INPUT의 REJECT 앞에 삽입 (REJECT 뒤에 넣으면 소용없다)
if ! iptables -C INPUT -p tcp -m tcp --dport 443 -m state --state NEW -j ACCEPT 2>/dev/null; then
  reject_line="$(iptables -L INPUT -n --line-numbers | awk '$2 == "REJECT" {print $1; exit}')"
  if [ -n "$reject_line" ]; then
    iptables -I INPUT "$reject_line" -p tcp -m tcp --dport 443 -m state --state NEW -j ACCEPT
  else
    iptables -A INPUT -p tcp -m tcp --dport 443 -m state --state NEW -j ACCEPT
  fi
fi
# 재부팅 후: 부팅 때 /etc/iptables/rules.v4가 복원되지 않고 ufw 규칙이 방화벽 역할을 한다.
if command -v ufw >/dev/null 2>&1; then
  ufw allow 443/tcp
fi
# iptables-persistent가 설치된 VM이면 즉시 적용분도 저장한다.
if command -v netfilter-persistent >/dev/null 2>&1; then
  netfilter-persistent save
fi

echo "[7/7] 확인 (VM 내부에서 이름을 직접 지정해 요청)"
# nginx reload 직후 첫 요청이 잠깐 실패할 수 있어(curl 코드 000) 몇 번 재시도한다.
check() {
  local host="$1" want="$2" code="000" attempt
  for attempt in 1 2 3 4 5; do
    code="$(curl -s -o /dev/null -m 10 -w '%{http_code}' --resolve "${host}:443:127.0.0.1" "https://${host}/" || true)"
    [ "$code" != "000" ] && break
    sleep 1
  done
  printf '  https://%-32s -> %s (기대: %s)\n' "${host}/" "$code" "$want"
}
check "$BASE" "302 (로그인 폼으로)"
check "$APP_HOST" "302 (로그인 폼으로)"
check "$CODE_HOST" "302 (code-server 로그인으로)"

echo
echo "완료. 브라우저에서 https://${BASE}/ 를 열어 아이디/비밀번호를 입력하세요."
echo "Oracle 콘솔 VCN Security List에 TCP 443 Ingress 규칙이 없으면 밖에서는 아직 안 열립니다."
echo "Streamlit(8501)은 외부에 열지 않는다 — 이 VM에 예전 'ufw allow 8501'/iptables 규칙이 남아 있다면 지우세요."
echo "인증서 자동 갱신 확인: systemctl list-timers | grep certbot"
