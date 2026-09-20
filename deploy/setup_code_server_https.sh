#!/usr/bin/env bash
# code-server(브라우저 VS Code)를 HTTPS 주소로 공개한다: nginx(443) → 127.0.0.1:8080.
#
# 사용법 (VM에서 root로): sudo bash deploy/setup_code_server_https.sh <도메인> [인증서 알림 이메일]
#   예) sudo bash deploy/setup_code_server_https.sh myname.duckdns.org me@example.com
#
# 이 스크립트를 돌리기 전에 사용자가 직접 해둬야 하는 것:
#   1. 도메인이 이 VM의 공인 IP를 가리킨다 (무료 DuckDNS 서브도메인이면 duckdns.org에서 IP 입력)
#   2. Oracle 콘솔 VCN Security List에 TCP 443 Ingress 규칙 추가 (80은 이미 열려 있음)
#
# 하는 일 (여러 번 돌려도 안전하다 — 이미 된 단계는 건너뛰거나 덮어쓴다):
#   - DNS가 이 VM을 가리키는지 확인 (아니면 Let's Encrypt 발급 한도만 낭비하므로 여기서 중단)
#   - certbot 설치, Let's Encrypt 인증서 발급(webroot 방식, 80번 포트 사용) + 자동 갱신
#   - nginx 사이트 설치: 80은 https로 리다이렉트, 443은 code-server로 프록시(WebSocket 포함)
#   - iptables INPUT 체인의 REJECT **앞에** 443 ACCEPT 삽입 + netfilter-persistent 저장
#     (이 VM의 Oracle 우분투 이미지는 REJECT가 ufw 체인보다 앞이라 ufw allow만으로는 안 열린다 —
#      deploy/DEPLOYMENT_ORACLE.md 14번 참고)
#
# 실패하면 nginx 설정을 직전 상태로 되돌리고 멈춘다. code-server 자체(127.0.0.1:8080)는 건드리지
# 않는다 — 계속 로컬 전용이라, 프록시가 죽어도 외부에 직접 노출되는 일은 없다.
set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${2:-}"
SITE_NAME="code-server"
SITES_AVAILABLE="/etc/nginx/sites-available/${SITE_NAME}"
SITES_ENABLED="/etc/nginx/sites-enabled/${SITE_NAME}"
WEBROOT="/var/www/html"

if [ "$(id -u)" -ne 0 ]; then
  echo "root 권한이 필요합니다: sudo bash $0 <도메인> [이메일]" >&2
  exit 1
fi
if [[ ! "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$ ]]; then
  echo "도메인 형식이 올바르지 않습니다: '${DOMAIN}'  (예: myname.duckdns.org)" >&2
  exit 1
fi

echo "[1/6] DNS 확인: ${DOMAIN} → 이 VM의 공인 IP"
server_ip="$(curl -fsS -m 10 https://api.ipify.org || true)"
dns_ip="$(getent ahostsv4 "$DOMAIN" | awk 'NR==1 {print $1}' || true)"
if [ -z "$server_ip" ] || [ -z "$dns_ip" ]; then
  echo "공인 IP(${server_ip:-확인 실패}) 또는 DNS(${dns_ip:-조회 실패})를 확인하지 못했습니다." >&2
  echo "도메인을 방금 만들었다면 1~2분 뒤 다시 시도하세요." >&2
  exit 1
fi
if [ "$server_ip" != "$dns_ip" ]; then
  echo "${DOMAIN} 은(는) ${dns_ip} 를 가리키는데 이 VM의 공인 IP는 ${server_ip} 입니다." >&2
  echo "DuckDNS 등에서 IP를 ${server_ip} 로 고친 뒤 다시 실행하세요." >&2
  exit 1
fi
echo "  OK (${DOMAIN} = ${server_ip})"

echo "[2/6] certbot 설치"
if ! command -v certbot >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y certbot
fi
mkdir -p "$WEBROOT"

backup=""
if [ -f "$SITES_AVAILABLE" ]; then
  backup="$(mktemp)"
  cp "$SITES_AVAILABLE" "$backup"
fi

rollback() {
  echo "실패 — nginx 설정을 직전 상태로 되돌립니다." >&2
  if [ -n "$backup" ]; then
    cp "$backup" "$SITES_AVAILABLE"
  else
    rm -f "$SITES_ENABLED" "$SITES_AVAILABLE"
  fi
  nginx -t >/dev/null 2>&1 && systemctl reload nginx || true
}

echo "[3/6] 인증서 발급용 임시 nginx 사이트 (80번, 인증서 확인 경로만 열고 나머지는 https로 리다이렉트)"
cat > "$SITES_AVAILABLE" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    location /.well-known/acme-challenge/ { root ${WEBROOT}; }
    location / { return 301 https://\$host\$request_uri; }
}
EOF
ln -sf "$SITES_AVAILABLE" "$SITES_ENABLED"
if ! nginx -t; then rollback; exit 1; fi
systemctl reload nginx

echo "[4/6] Let's Encrypt 인증서 발급 (자동 갱신 포함)"
certbot_args=(certonly --webroot -w "$WEBROOT" -d "$DOMAIN" --non-interactive --agree-tos
              --deploy-hook "systemctl reload nginx")
if [ -n "$EMAIL" ]; then
  certbot_args+=(--email "$EMAIL")
else
  certbot_args+=(--register-unsafely-without-email)
fi
if ! certbot "${certbot_args[@]}"; then rollback; exit 1; fi

echo "[5/6] 최종 nginx 사이트 (443 → code-server, WebSocket 포함)"
cat > "$SITES_AVAILABLE" <<EOF
map \$http_upgrade \$code_server_connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    location /.well-known/acme-challenge/ { root ${WEBROOT}; }
    location / { return 301 https://\$host\$request_uri; }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${DOMAIN};

    ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:code_server_ssl:10m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$code_server_connection_upgrade;
        proxy_set_header Accept-Encoding gzip;
        proxy_read_timeout 86400;
    }
}
EOF
if ! nginx -t; then rollback; exit 1; fi
systemctl reload nginx

echo "[6/6] 방화벽: iptables INPUT의 REJECT 앞에 443 허용 + 저장"
if ! iptables -C INPUT -p tcp -m tcp --dport 443 -m state --state NEW -j ACCEPT 2>/dev/null; then
  reject_line="$(iptables -L INPUT -n --line-numbers | awk '$2 == "REJECT" {print $1; exit}')"
  if [ -n "$reject_line" ]; then
    iptables -I INPUT "$reject_line" -p tcp -m tcp --dport 443 -m state --state NEW -j ACCEPT
  else
    iptables -A INPUT -p tcp -m tcp --dport 443 -m state --state NEW -j ACCEPT
  fi
fi
if command -v netfilter-persistent >/dev/null 2>&1; then
  netfilter-persistent save
else
  echo "netfilter-persistent가 없어 재부팅 후에는 443 규칙이 사라집니다 — iptables-persistent를 설치하세요." >&2
fi

echo
echo "완료. 확인:"
echo "  https://${DOMAIN}/   → code-server 로그인 화면(비밀번호 입력)이 떠야 합니다."
echo "Oracle 콘솔 VCN Security List에 TCP 443 Ingress 규칙이 없으면 밖에서는 아직 안 열립니다."
echo "인증서 자동 갱신 확인: systemctl list-timers | grep certbot"
