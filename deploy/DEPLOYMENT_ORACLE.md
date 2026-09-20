# Oracle Cloud 무료 VM 배포 가이드

Codespace를 꺼도 Streamlit 앱 + `scheduler/run_scheduler.py`(관심종목 스캔·주간 리포트·시장 스냅샷·
야간 미세튜닝)가 계속 돌게 하기 위한 절차. DB는 별도 서버 없이 지금과 동일한 로컬 SQLite
(`data/quant.db`)를 VM의 로컬 디스크에 그대로 둔다 — 이 규모(수백 종목 × 수년 일봉)에서는 관리형
DB로 옮길 필요가 없다.

계정 가입·VM 발급·SSH 접속은 본인만 할 수 있는 단계라 아래는 직접 따라 하는 가이드다. 리포에 있는
`deploy/setup_vm.sh` 는 그중 반복 작업(패키지 설치/systemd 등록/방화벽)만 대신 해준다.

무인 에이전트가 대신 못 하고 사람이 직접 로그인해서 처리해야 할 대기 항목은
[`PENDING_MANUAL_LOGIN_ACTIONS.md`](./PENDING_MANUAL_LOGIN_ACTIONS.md)에 모아둔다.

## 0. 사전 준비

- Oracle Cloud 계정 (신용카드 등록은 필요하지만 Always Free 리소스는 과금되지 않음)
- 로컬에 SSH 키 페어 (`ssh-keygen -t ed25519` 로 없으면 생성)
- 이 리포에 대한 git 접근 권한(비공개 리포면 GitHub PAT 또는 배포용 SSH 키)

## 1. Oracle Cloud VM 발급 (Always Free)

1. https://cloud.oracle.com 가입 → 홈 리전 선택(가까운 리전, 이후 변경 어려움).
2. 콘솔 → **Compute → Instances → Create Instance**.
3. Image: **Ubuntu 24.04** (또는 최신 LTS).
4. Shape: **Change Shape → Ampere → VM.Standard.A1.Flex** 선택 후 OCPU 2 / Memory 12GB로 맞춘다
   (2026-06-15부로 Always Free 한도가 4 OCPU/24GB → 2 OCPU/12GB로 축소됨 — Always Free 표시가 붙는
   조합만 골라야 과금되지 않는다).
5. Boot volume: 기본값 사용 (Always Free 총 200GB 블록스토리지 한도 안에서 조정 가능).
6. SSH 키: 로컬 공개키(`~/.ssh/id_ed25519.pub`) 업로드.
7. **Create** → 프로비저닝 완료 후 Public IP 확인.

### 1-1. (자주 발생) "Out of host capacity" 에러 시 자동 재시도

A1.Flex는 인기 리전에서 수요가 많아 콘솔에서 바로 생성하면 `Out of host capacity` 에러가 흔하다.
`deploy/oracle_capacity_retry.sh`가 OCI CLI로 인스턴스 생성을 반복 시도한다(기본 60초 간격, capacity
에러가 아닌 다른 결과가 나오면 멈춤).

```bash
# 로컬 머신(또는 어디서든 계속 켜둘 수 있는 환경)에서
brew install oci-cli   # 또는 pip install oci-cli
oci setup config       # 콘솔 Profile > API Keys 에서 발급한 키로 인증 설정

export COMPARTMENT_ID=ocid1.compartment...        # Identity > Compartments
export IMAGE_ID=ocid1.image...                     # Compute > Images (Ubuntu 24.04 aarch64)
export SUBNET_ID=ocid1.subnet...                    # Networking > VCN > Subnets
export AVAILABILITY_DOMAINS="AD-1,AD-2,AD-3"        # 콤마로 여러 AD 순회 (Create Instance 화면에 표시됨)
# SSH_PUBLIC_KEY_FILE 기본값은 ~/.ssh/id_ed25519.pub, 필요시 덮어쓰기

bash deploy/oracle_capacity_retry.sh
```

성공하면 인스턴스 OCID/Public IP가 출력된다. 이후 단계는 아래 2번부터 그대로 진행.

## 2. 네트워크(방화벽) 설정 — 콘솔 쪽

OS 방화벽(`setup_vm.sh`가 ufw로 처리)과는 별개로, Oracle 콘솔의 **VCN Security List**(또는 VM에
붙은 NSG)에서도 인그레스 규칙을 열어야 외부에서 접속된다.

1. 콘솔 → **Networking → Virtual Cloud Networks** → 해당 VCN → **Security Lists** → Default
   Security List.
2. **Add Ingress Rules**:
   - Source CIDR `0.0.0.0/0`, IP Protocol `TCP`, Destination Port `8501` (Streamlit)
   - (code-server 8080은 여기서 **열지 않는다** — 셸 권한을 통째로 주는 IDE라 SSH 터널로만 접속한다,
     14번 참고)
   - (SSH용 22번은 기본 이미지 생성 시 이미 열려 있음)

## 3. SSH 접속 + 리포 클론 + .env 준비

```bash
ssh ubuntu@<PUBLIC_IP>
sudo git clone <이 리포 URL> /opt/quant
cd /opt/quant
sudo cp .env.example .env
sudo nano .env   # FRED_API_KEY / GEMINI_API_KEYS 등 실제 값 채우기
```

`.env`는 git에 커밋되지 않는 파일이라 로컬에서 쓰던 값을 그대로 복사해 붙여넣으면 된다
(`scp .env ubuntu@<PUBLIC_IP>:/tmp/.env` 로 옮긴 뒤 `sudo mv /tmp/.env /opt/quant/.env` 도 가능).

## 4. 자동 설정 스크립트 실행

```bash
cd /opt/quant
sudo bash deploy/setup_vm.sh
```

이 스크립트가 하는 일:
- Python 3.12 + venv 생성, `requirements.txt` 설치
- 전용 시스템 계정(`quant`)으로 서비스 실행(root로 앱을 돌리지 않기 위함)
- `deploy/quant-streamlit.service` / `deploy/quant-scheduler.service` 를 systemd에 등록해
  **부팅 시 자동 시작 + 죽으면 자동 재시작**하도록 설정
- `deploy/quant-vm-health.service` + `.timer`를 등록해 디스크/메모리 사용률을 주기적으로 확인하고
  임계값 초과 시 텔레그램 알림(11번 참고)
- `deploy/quant-auto-deploy.service` + `.timer`를 등록해 GitHub main에 새 커밋이 올라오면 자동으로
  `git pull --ff-only` + 서비스 재시작(12번 참고)
- OS 방화벽(ufw)에서 8501 허용

## 5. 확인

```bash
sudo systemctl status quant-streamlit
sudo systemctl status quant-scheduler
sudo journalctl -u quant-scheduler -f   # 스케줄러 실시간 로그(장 마감 스캔/야간 튜닝 등)
```

브라우저에서 `http://<PUBLIC_IP>:8501` 접속되면 성공. `data/quant.db` 는 최초 접속 시
`core.db.init_db()` 가 자동 생성한다.

## 5-1. 서비스 죽으면 텔레그램으로 자동 알림

`codex-telegram` / `quant-streamlit` / `quant-scheduler` 세 서비스는 죽거나(비정상 종료) 재시작될
때마다 systemd의 `OnFailure=` 메커니즘으로 자동으로 텔레그램 알림을 보낸다. 별도 감시 프로세스를
새로 띄우는 게 아니라, 각 서비스 유닛 파일의 `[Unit]`에 붙은 `OnFailure=quant-alert@%n.service`
한 줄이 전부다 — 그 서비스가 실패하는 순간 systemd가 `deploy/quant-alert@.service`(템플릿 유닛)를
인스턴스화해서 대신 실행하고, 이 유닛이 기존 `deploy/send_telegram_alert.sh`(codex-telegram
러너와 같은 봇/채팅을 쓰는 공용 헬퍼)를 호출해 "⚠️ \<실패한 유닛 이름\> 실패/재시작됨 (시각)"
메시지를 보낸다.

- `quant-alert@.service`는 템플릿 유닛이라 그 자체를 `enable --now` 하지 않는다 —
  `setup_vm.sh`(공용 3서비스 경로)와 `deploy/codex_telegram/install.sh`(codex-telegram 단독 설치
  경로) 둘 다 `/etc/systemd/system/`에 파일만 복사해두고, 필요할 때 systemd가 알아서
  인스턴스화한다.
- 알림 봇/채팅 설정은 새로 필요 없다 — `send_telegram_alert.sh`가 이미 codex-telegram이 쓰는
  `/opt/quant/.codex-telegram-runtime/telegram.env`를 그대로 읽는다.

**수동 테스트 (실제로 서비스를 죽이는 조작이니 운영 중에는 주의해서 실행)**:

```bash
sudo systemctl kill --signal=SIGKILL quant-streamlit
```

몇 초 안에 텔레그램으로 "⚠️ quant-streamlit.service 실패/재시작됨 (...)" 메시지가 오면 정상이다.
세 서비스 모두 `Restart=always` 또는 `Restart=on-failure`가 걸려 있어 알림이 간 뒤 자동으로 다시
살아난다(상태는 `systemctl status quant-streamlit`로 확인). `codex-telegram` / `quant-scheduler`도
서비스 이름만 바꿔 같은 방식으로 테스트할 수 있다.

메시지 문구를 바꾸고 싶으면 `deploy/quant-alert@.service`의 `ExecStart` 한 줄만 고치면 된다
(`%i`가 실패한 유닛 이름으로 치환된다). 수정 후에는 VM에서 `sudo cp deploy/quant-alert@.service
/etc/systemd/system/ && sudo systemctl daemon-reload`로 반영한다 — 템플릿 유닛이라 재시작할
필요는 없다.

## 6. 코드 업데이트 배포

> 이 수동 절차는 이제 기본적으로 필요 없다 — `quant-auto-deploy` 타이머(12번 참고)가 5분마다
> 자동으로 감지해서 pull + 재시작까지 한다. 지금 당장 반영하고 싶어서 5분을 못 기다리거나,
> 타이머를 껐을 때만 아래를 손으로 실행한다.

로컬(또는 Codespace)에서 작업한 변경사항을 반영하려면:

```bash
ssh ubuntu@<PUBLIC_IP>
cd /opt/quant
sudo git pull
sudo -u quant .venv/bin/pip install -r requirements.txt   # 의존성 바뀐 경우만
sudo systemctl restart quant-streamlit quant-scheduler
```

## 7. GitHub Actions 야간 튜닝과의 관계

`.github/workflows/nightly_tuning.yml` (매일 00:05 KST)은 이 VM과 **완전히 독립적으로** 계속
동작한다 — GitHub 서버에서 실행되고 결과를 `data/nightly_tuning_leaderboard.json`으로 리포에
커밋한다. `scheduler/run_scheduler.py`의 `strategy_nightly_tuning_job()`은 이 VM의 로컬 SQLite
(`StrategyTuningRun`/`StrategyTuningResult`)에 별도로 쌓인다 — 저장소가 다른 두 결과지만,
`app/pages/13_야간_미세튜닝_리더보드.py`가 이미 **둘을 합쳐서** 보여주도록 짜여 있다(로컬 DB
결과 + 커밋된 JSON을 함께 읽어 test 구간 초과수익 기준 상위 10개를 뽑음). 이 VM에서
`git pull`만 해두면 GitHub Actions 쪽 결과도 자동으로 리더보드에 반영된다 — 아무 설정도 추가로
필요 없다.

## 8. (선택) HTTPS/도메인

지금은 `http://<PUBLIC_IP>:8501`로 평문 접속이다. 본인만 쓰는 대시보드라면 이 상태로도 충분하지만,
도메인을 붙이고 싶으면 nginx를 리버스 프록시로 두고 Let's Encrypt(`certbot`)로 인증서를 발급받는
방식이 표준적이다 — 필요해지면 별도로 셋업해줄 수 있다.

## 9. 백업

`data/quant.db` 하나가 전략/알림 이력/야간튜닝 결과의 전부다. 유실 방지를 위해 가끔
`scp ubuntu@<PUBLIC_IP>:/opt/quant/data/quant.db ./backup/quant-$(date +%F).db` 로 로컬에 받아
두는 것을 권장한다(자동화는 필요해지면 cron으로 추가 가능).

## 10. (2026-09-14, 정정) 리서치 에이전트는 이 VM이 아니라 Codespace에서 돈다

이 VM은 **완성된 서비스를 배포/서빙하는 역할**로 한정한다(Streamlit 앱 + `scheduler/
run_scheduler.py`의 상시 잡들 — 이건 전부 "이미 확정된 제품 기능"이라 여기 남아있는 게 맞다).

2026-09-14에 한 차례 이 VM에 야간 무인 리서치 에이전트 7개(B~H, systemd 타이머)를 배포했다가,
"리서치는 Codespace에서, VM은 완성된 결론만 서비스로 배포하는 역할"이라는 사용자의 원래 의도와
어긋난다는 걸 확인하고 **VM에서 완전히 제거했다**(systemd 서비스/타이머 파일 삭제,
`deploy/research_agents/`도 저장소에서 제거). 그 에이전트들의 페르소나 프롬프트는
`research_agents/`(저장소 최상위)로 옮겨졌고, 이제 **Codespace 세션 안에서 Claude Code가
서브에이전트로 직접 실행**한다 — VM에는 배포하지 않는다.

**알아둘 제약**: GitHub Codespace는 일정 시간 조작이 없으면 자동으로 정지되므로, "매일 밤
정해진 시각에 자동 실행"은 안 되고 사용자가 Codespace를 열어 요청할 때만 돈다. 진짜 매일 밤
무인 자동 실행이 필요해지면, VM이나 항상 켜진 Codespace가 아니라 **GitHub Actions 스케줄
워크플로**(이 저장소가 이미 `.github/workflows/nightly_tuning.yml`로 쓰고 있는 방식과 동일 —
VM/Codespace 없이 GitHub이 자체적으로 임시 실행 환경을 띄웠다 없앤다)가 이 프로젝트의 기존
관례에 맞는 다음 후보지다(Claude Pro 로그인 자격증명을 GitHub Secrets로 안전하게 주입하는
추가 작업 필요 — 아직 안 함).

## 11. VM 헬스체크(디스크/메모리) 알림

Always Free 티어는 디스크/메모리가 넉넉하지 않다. `deploy/vm_health_check.sh`가
`quant-vm-health.timer`(부팅 5분 후 시작, 이후 15분마다)로 주기 실행되며 루트 파티션(`/`) 사용률과
메모리 사용률을 확인해서 임계값을 넘으면 `deploy/send_telegram_alert.sh`로 텔레그램 알림을 보낸다.
`codex-telegram`이 쓰는 큐 상태(`/opt/quant/.codex-telegram-state/`)와는 별개로
`/opt/quant/.vm-health-state/`에 자체 상태(마지막 알림 시각)를 저장해서, 임계값을 한 번 넘은 뒤로는
회복될 때까지 6시간에 한 번만 재알림하고(스팸 방지), 회복되면 "복구됨" 메시지를 한 번 보내고
다음 초과에 대비해 상태를 지운다. 디스크/메모리는 서로 독립된 조건으로 취급한다(하나만 알림 중이어도
다른 하나는 별도로 추적).

**기본 임계값**: 디스크 85%, 메모리 90% (메모리는 `free`의 available 컬럼 기준 — 회수 가능한
페이지캐시는 "사용중"으로 안 침). `deploy/setup_vm.sh`가 등록하는 유닛에는 값이 하드코딩돼 있지
않고 스크립트 기본값을 그대로 쓰므로, 바꾸려면 systemd 쪽에서 환경변수를 얹어야 한다:

```bash
sudo systemctl edit quant-vm-health.service
```

에디터가 열리면(드롭인 파일 생성) 아래처럼 채운다:

```ini
[Service]
Environment=DISK_THRESHOLD_PERCENT=80
Environment=MEM_THRESHOLD_PERCENT=85
Environment=ALERT_COOLDOWN_SECONDS=21600
```

저장 후:

```bash
sudo systemctl daemon-reload
```

(타이머가 다음 주기에 알아서 새 값으로 실행한다 — 서비스 자체는 oneshot이라 재시작할 필요 없음.)

**동작 확인**:

```bash
sudo systemctl list-timers quant-vm-health.timer   # 다음 실행 예정 시각
sudo journalctl -u quant-vm-health                 # 실행 로그(정상일 땐 출력 없음 — 조용한 게 정상)
sudo systemctl start quant-vm-health.service        # 지금 바로 1회 실행해보기
```

**강제로 알림 한 번 발생시켜보기** (실제로 디스크/메모리가 꽉 찰 때까지 기다리지 않고 알림 경로
전체 — 텔레그램 발송까지 — 를 검증하고 싶을 때):

```bash
sudo systemctl edit quant-vm-health.service
# [Service] 아래에 Environment=DISK_THRESHOLD_PERCENT=0 추가 → 저장 (무조건 임계값 초과 상태가 됨)
sudo systemctl daemon-reload
sudo systemctl start quant-vm-health.service
# 텔레그램으로 "⚠️ ... 디스크(/) 사용률 ... 초과" 메시지가 오는지 확인

sudo systemctl revert quant-vm-health.service   # 드롭인 제거, 기본 임계값(85%)으로 원복
sudo systemctl daemon-reload
sudo systemctl start quant-vm-health.service     # 정상 범위로 "복구됨" 알림이 한 번 더 오는지 확인
# (원복 후에도 /opt/quant/.vm-health-state/disk.alerting 이 남아있는 상태에서 실행해야
#  "복구됨" 메시지가 뜬다 — 위 두 명령을 순서대로 실행하면 자연스럽게 그렇게 됨)
```

## 12. 자동 배포 (`quant-auto-deploy` 타이머)

6번 절차(`git pull` → 재시작)를 사람이 SSH로 들어와 손으로 할 필요가 없도록, GitHub main에
새 커밋이 올라오면 VM이 스스로 감지해서 반영하는 systemd 타이머다. `deploy/setup_vm.sh`가
`deploy/quant-auto-deploy.service`(oneshot, `deploy/auto_deploy.sh` 실행) +
`deploy/quant-auto-deploy.timer`(부팅 2분 후 1회, 이후 5분마다)를 함께 설치·활성화한다.

**동작**: 매번 `git fetch`로 `origin/main`만 조회하고, 로컬 `HEAD`와 같으면 아무 것도 안 하고
조용히 끝난다(가장 흔한 경우). 다를 때만 `sudo -u quant git pull --ff-only`를 시도하고,
성공하면 `requirements.txt`가 이번 범위에서 바뀌었는지 확인해 바뀌었을 때만 먼저
`pip install -r requirements.txt`를 실행한다(실패하면 서비스는 재시작하지 않고 기존 버전을
그대로 둔 채 텔레그램으로 알리고 종료). 그다음 **서비스를 재시작하기 전에 테스트 게이트를
돈다** — `tests/`(프로젝트 venv, `pytest`) + `deploy/codex_telegram/test_runner.py` /
`deploy/test_experiment_supervisor.py`(시스템 `python3` — 이 두 파일이 검증하는
`runner.py`/`experiment_supervisor.py` 자체가 venv 없이 시스템 python으로 도는 stdlib-only
프로세스라서). 이 게이트가 실패하면 `codex-telegram`/`quant-streamlit`/`quant-scheduler`
세 서비스를 **재시작하지 않고**(기존 버전이 계속 돎) 실패한 pytest 출력 뒷부분과 함께
텔레그램으로 알린 뒤 종료한다 — 워킹트리 자체는 이미 새(깨진) 커밋으로 옮겨간 상태라, 다음
타이머 틱에서는 `local HEAD == origin/main`이라 조용히 no-op으로 끝난다(같은 커밋을 반복
테스트하거나 반복 알림하지 않음). 그다음에 새 커밋이 푸시되면 그걸로 다시 테스트를 시도한다.
테스트까지 통과하면 세 서비스를 모두 재시작하고 배포 결과(구→신 커밋, 커밋 개수, 재시작한
서비스 목록)를 텔레그램으로 한 번 알린다 — 직전에 pull 실패/테스트 실패 상태였다면 "복구됨"
문구도 함께 붙는다. 테스트 게이트의 타임아웃은 기본 240초(`AUTO_DEPLOY_TEST_TIMEOUT_SECONDS`
로 조절 가능)이며, 시간 초과도 실패로 취급해 서비스를 건드리지 않는다.

**비파괴 원칙(★)**: 여기서 쓰는 git 명령은 `git fetch`와 `git pull --ff-only`, 그리고
`data/cache/fred_*.csv` 하나만 대상으로 하는 `git checkout --` 뿐이다. 이 FRED 캐시 파일들은
`.gitignore`가 이미 "VM에서 다시 만들어져도 되는 캐시"로 명시적으로 추적 예외를 둔 파일이라,
이 VM의 `quant-scheduler`가 로컬에서 독립적으로 새로고침해도 매번 `pull`을 다시 시도하기 전에
안전하게 되돌린다(외부 API에서 그대로 재요청 가능한 멱등 데이터라 버려도 다음 스케줄러
주기에 다시 채워짐). 그 외 파일에서 fast-forward가 안 되는 상황(히스토리 분기, 로컬 수정이
막고 있음, 충돌 등)이면 **그 자리에서 즉시 포기**하고 워킹트리는 손도 대지 않은 채 텔레그램으로
"수동 확인 필요" 알림만 보낸 뒤 종료한다. `git reset --hard`, `git clean`, 범용 `git checkout .`,
강제 push, stash/drop 같은 자동 복구 시도는 절대 하지 않는다 — VM 워킹트리에는 지우면 안 되는
로컬 수정 파일과 미커밋 리서치 결과물이 실제로 쌓여 있을 수 있기 때문이다
(`PENDING_MANUAL_LOGIN_ACTIONS.md` 참고). 이 실패 알림은 같은 문제가 계속되는 동안
`AUTO_DEPLOY_ALERT_COOLDOWN_SECONDS`(기본 21600초 = 6시간)마다 한 번만 다시 보낸다 — 매
5분마다 재알림해서 스팸이 되는 걸 막기 위함이다(2026-09-18 실제로 `fred_*.csv` 충돌로
178개가 쌓인 뒤 추가됨).

**확인**:
```bash
systemctl list-timers quant-auto-deploy.timer   # 다음 실행 예정 시각
journalctl -u quant-auto-deploy                 # 배포 이력/에러 로그 (평소엔 no-op이라 거의 비어있음)
```

**수동 배포로 되돌리고 싶으면**:
```bash
sudo systemctl disable --now quant-auto-deploy.timer
```
이후로는 6번 절차대로 손으로 `git pull` + `systemctl restart` 하면 된다.

**알아둘 트레이드오프**: 배포가 성공하면 `codex-telegram` 서비스도 재시작되는데, 그 시점에
텔레그램 에이전트가 작업을 실행 중이었다면 그 작업이 중단된다. 다만 `runner.py`가 종료 시그널을
받으면 실행 중이던 작업을 그냥 죽이지 않고 `retry` 상태로 표시해두므로(다음 실행 때 자동으로
이어서 재개), 데이터 유실이 아니라 그 작업이 몇 분 늦게 끝나는 정도의 사소하고 감수할 만한
불편이다. 테스트 게이트 때문에 새 커밋이 있을 때만 배포가 최대 수 분(로컬 기준 `tests/`
866개가 약 50초, VM은 더 느릴 수 있음 + deploy 유닛테스트) 더 걸릴 수 있는데, 평소 대부분의
타이머 틱은 새 커밋이 없어 테스트 자체를 돌리지 않으므로 이 지연은 배포가 실제로 일어나는
그 순간에만 발생한다.

## 13. 관제 허브 (`hub/`) — 최상위 진입점

VM의 IP만 치면(`http://<PUBLIC_IP>/`) 이 VM에서 돌고 있는 앱/엔진 전체를 카드 목록으로 보여주는
최상위 대시보드가 뜨도록 하는 모듈. `hub/server.py`가 stdlib `http.server`만으로 127.0.0.1:8000에서
돌고(신규 pip 의존성 없음), nginx가 80번 포트(`default_server`)를 여기로 프록시한다
(`deploy/nginx-quant.conf`). 슬롯 목록은 `hub/apps_registry.py`의 `SLOTS`에 선언돼 있고, 카드를
누르면:

- `kind="web"` (예: 퀀트 대시보드): 그 앱 자신의 포트(예: `:8501`)로 직접 이동 — nginx가 경로를
  다시 프록시하지 않으므로 Streamlit `--server.baseUrlPath` 같은 설정을 건드릴 필요가 없다.
- `kind="report"` (예: 실험 슈퍼바이저): `hub/server.py`가 `report_glob` 패턴에 맞는 파일 중
  가장 최근 것을 그대로 서빙한다(예: `.experiment-control/reports/*.html`).
- `kind="engine"` (자체 웹 UI가 없는 백그라운드 서비스): `/status/<id>` 상태 페이지로 이동해
  `systemctl show`로 조회한 ActiveState/SubState/가동 시각을 보여준다(참고: `quant` 계정은 sudo
  없이도 이 읽기 전용 조회는 가능하지만 `journalctl`은 `adm`/`systemd-journal` 그룹이 아니라 권한이
  없어 로그는 보여주지 않는다).

새 서비스를 VM에 추가하면 `hub/apps_registry.py`에 `AppSlot` 하나만 추가하면 허브에 자동으로
카드가 생긴다. 최초 설치(신규 VM은 `setup_vm.sh`가 자동으로 처리하지만, 이미 떠 있는 VM에
`quant-hub.service`/nginx 사이트를 추가로 올리는 것은 `sudo`가 필요해 사람이 직접 해야 함)는
[`PENDING_MANUAL_LOGIN_ACTIONS.md`](./PENDING_MANUAL_LOGIN_ACTIONS.md) 4번 참고.

## 14. 브라우저 코드 스페이스 (code-server) — GitHub Codespaces 대체

GitHub Codespaces는 idle이면 꺼져서 "이 VM에서 언제든 브라우저로 코딩"이 안 된다. 이 VM에는
이미 `code-server`(브라우저에서 도는 VS Code)가 `ubuntu` 계정의 `code-server@ubuntu.service`로
설치·기동돼 있다(패키지 기본 설정은 `127.0.0.1:8080`만 바인딩 — 외부 접속 불가, SSH 터널로만
접속 가능한 상태).

**지금 당장, 추가 조치 없이 쓰는 법 (가장 안전, 추천)**:

```bash
ssh -L 8080:localhost:8080 ubuntu@<PUBLIC_IP>
```

터널을 연 채로 로컬 브라우저에서 `http://localhost:8080` 접속 → code-server 로그인 화면(비밀번호는
`ubuntu` 계정의 `~/.config/code-server/config.yaml`에 있음).

**Codespace에서 쓰는 법**: SSH 키가 이미 있는 GitHub Codespace 터미널에서
`ssh -N -L 8080:localhost:8080 ubuntu@<PUBLIC_IP>`(또는 `~/.ssh/config`에 잡아둔 별칭)를 실행하면,
VS Code 하단 **Ports 탭**에 8080이 자동으로 뜬다 — 그 행의 지구본 아이콘으로 브라우저에서 연다.
Codespaces 포트 포워딩은 기본이 비공개(GitHub 로그인한 본인만)라 별도 인증이 하나 더 붙는다.
Codespace가 idle로 꺼지면 터널도 함께 끊기므로 다시 열어주면 된다.

**허브 카드**: 허브의 "브라우저 코드 스페이스" 카드(`kind="link"`)는 아래 HTTPS 주소로 바로 연결된다
(`hub/apps_registry.py`의 `url`). DuckDNS 장애나 공인 IP 변경으로 주소가 안 열릴 때는 위 SSH 터널이 대안이다.

**HTTPS 주소로 공개하기 (2026-09-20 결정, 무료 DuckDNS + Let's Encrypt)**: SSH 터널은 Codespace를 먼저
열어야 해서 불편하므로, 아무 기기 브라우저에서 URL + 비밀번호만으로 들어오게 한다. 8080을 그대로
여는 게 아니라(평문 HTTP + 비밀번호 하나로 `sudo` 가능한 셸을 노출하는 셈이라 안 함) **nginx가 443에서
TLS를 끝내고 `127.0.0.1:8080`으로 프록시**한다 — code-server 자체는 계속 로컬 전용이다.

1. https://www.duckdns.org 에서 GitHub 등으로 로그인해 무료 서브도메인을 만들고, IP에 이 VM의 공인 IP를 넣는다.
2. Oracle 콘솔 VCN Security List에 `TCP / 443 / 0.0.0.0/0` Ingress 규칙 추가 (80은 이미 열려 있음).
3. VM에서: `sudo bash /opt/quant/deploy/setup_code_server_https.sh <이름>.duckdns.org [이메일]`
   — DNS 확인 → certbot 설치·인증서 발급(자동 갱신) → nginx 사이트 설치 → 443 허용(iptables + ufw).
   실패하면 nginx 설정을 되돌리고 멈춘다. 여러 번 돌려도 안전하다.
4. `https://<이름>.duckdns.org/` 접속 → code-server 로그인(비밀번호는 `~/.config/code-server/config.yaml`).
   (현재 운영 중인 주소: `https://hessejeong.duckdns.org/`, 인증서는 certbot 타이머가 자동 갱신)

이제 비밀번호가 평문으로 오가지는 않지만, 비밀번호 하나가 곧 VM 셸이다 — 강한 비밀번호(현재 24자)를
유지하고 쉬운 것으로 바꾸지 말 것(code-server가 로그인 시도를 분당 몇 회로 제한하긴 한다).
DuckDNS는 무료·후원 기반 서비스라 드물게 불안정할 수 있고, VM 공인 IP가 바뀌면(인스턴스 중지 후
재시작 등 — 예약 IP가 아니라면) DuckDNS 화면에서 IP를 직접 고쳐야 한다. 그때는 위 SSH 터널이 대안이다.

**알아둘 것 — 이 VM의 방화벽은 지금 상태와 재부팅 후 상태가 다르다** (2026-09-20 확인):
- **지금(부팅 후 계속 켜져 있는 동안)**: `/etc/iptables/rules.v4`에서 온 Oracle 기본 `REJECT`가 INPUT 체인에서
  ufw 체인보다 **앞에** 있어서, `ufw allow`만 하면 패킷이 REJECT에서 끝나 ufw 체인에 도달하지 못한다
  (8080으로 확인 — Oracle VCN Security List는 통과하는데 VM 안에서 거절됨). 22/80/8501은 그 REJECT
  **앞에** 직접 `iptables -I INPUT ... -j ACCEPT`로 넣어둔 것이라 통한다.
- **재부팅 후**: `iptables-persistent`/`netfilter-persistent` 패키지가 **제거된 상태(dpkg `rc`)**라 부팅 때
  `rules.v4`를 복원하는 장치가 없다. 그러면 수동으로 넣은 iptables ACCEPT와 REJECT가 모두 사라지고
  **ufw 규칙이 방화벽 역할**을 한다(ufw는 부팅 시 자동 활성화). 즉 새 포트를 공개하려면 **iptables ACCEPT(즉시
  적용) + `ufw allow`(재부팅 후 유지) 둘 다** 넣어야 한다 — `setup_code_server_https.sh`가 그렇게 한다.
- 기존 22/80/8501의 iptables 규칙은 재부팅 후 사라지지만 ufw에도 같은 규칙이 있어 접속은 유지된다.
