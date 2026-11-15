#!/usr/bin/env bash
# 과부하 비상 정지(관제 허브 /emergency)가 ubuntu 계정 프로세스까지 멈출 수 있게 하는 root 도우미 설치. 한 번만 실행:
#   sudo bash /opt/quant/deploy/proc_control/setup.sh
# 하는 일: quant-proc-signal 을 /usr/local/sbin 에 복사하고, quant 계정이 그 파일 하나만 비밀번호 없이 sudo 로 실행하게
# /etc/sudoers.d/quant-proc-signal 한 줄을 넣는다(visudo 로 문법 확인 후). 되돌리기: 두 파일을 지우면 된다.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
install -o root -g root -m 755 "$here/quant-proc-signal" /usr/local/sbin/quant-proc-signal
tmp="$(mktemp)"
echo 'quant ALL=(root) NOPASSWD: /usr/local/sbin/quant-proc-signal' > "$tmp"
visudo -cf "$tmp" >/dev/null
install -o root -g root -m 440 "$tmp" /etc/sudoers.d/quant-proc-signal
rm -f "$tmp"
echo "설치 완료: /usr/local/sbin/quant-proc-signal, /etc/sudoers.d/quant-proc-signal"
