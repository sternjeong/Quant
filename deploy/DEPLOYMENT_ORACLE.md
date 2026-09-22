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
   - Source CIDR `0.0.0.0/0`, IP Protocol `TCP`, Destination Port `80`, 그리고 `443` (HTTPS 게이트웨이 —
     14번). Streamlit 8501과 code-server 8080은 여기서 **열지 않는다**: 둘 다 로컬 전용 포트이고, 게이트웨이의
     로그인 뒤에서만 `app.`/`code.` 주소로 접속한다.
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
- OS 방화벽(ufw)에서 22/80 허용 (8501은 열지 않는다 — 14번 게이트웨이 뒤에서만 접속)

## 5. 확인

```bash
sudo systemctl status quant-streamlit
sudo systemctl status quant-scheduler
sudo journalctl -u quant-scheduler -f   # 스케줄러 실시간 로그(장 마감 스캔/야간 튜닝 등)
```

VM 안에서 `curl -s http://127.0.0.1:8501/_stcore/health`가 `ok`이면 앱은 떠 있는 것이고, 밖에서는 14번 게이트웨이를
설치한 뒤 `https://app.<도메인>/`(로그인 필요)으로 접속한다. `data/quant.db` 는 최초 접속 시
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

## 8. HTTPS/도메인

2026-09-20부터 무료 DuckDNS 도메인 + Let's Encrypt 인증서로 **HTTPS 게이트웨이**를 쓴다 — 기본 도메인이
관제 허브, `app.`이 이 Streamlit 대시보드, `code.`이 브라우저 코드 스페이스다. 구성·설치는 14번 참고.
(`http://<PUBLIC_IP>:8501` 평문 직접 접속은 2026-09-20에 방화벽에서 닫았다.)

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

**비파괴 원칙(★)**: 여기서 쓰는 git 명령은 `git fetch`와 `git pull --ff-only`, 그리고 좁은 예외 두 가지 —
`data/cache/fred_*.csv` 하나만 대상으로 하는 `git checkout --`, `PROGRESS.md` 하나에 한정한 "백업 → 되돌림 → pull → 다시 얹기"(아래) — 뿐이다. 이 FRED 캐시 파일들은
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

**`PROGRESS.md` 충돌은 자동으로 푼다** (2026-09-20, `deploy/progress_reconcile.sh`): VM의 리서치 에이전트/실험 슈퍼바이저는
루트 `PROGRESS.md` 끝에 진행 기록을 *미커밋으로* 덧붙이고, 개발 쪽 커밋도 같은 파일에 항목을 추가한다. 예전에는 원격이 이
파일을 바꾸는 커밋을 올릴 때마다 `git pull --ff-only`가 "로컬 변경이 덮어써진다"며 막혀 자동배포가 통째로 멈췄고, 사람이 VM에서
손으로 커밋·리베이스·푸시해야 했다. 이제는 **(a) VM의 `PROGRESS.md`가 미커밋으로 수정돼 있고 (b) 새 커밋도 이 파일을 바꿀 때만**
① 로컬 파일을 바이트 단위로 확인한 백업(`.auto-deploy-state/PROGRESS.local.<시각>`, 최근 10개 보관)으로 저장하고 ② 이 파일 하나만
HEAD로 되돌려 pull을 통과시킨 뒤 ③ 백업의 로컬 추가분을 새 upstream 위에 3-way *union* 병합(`git merge-file --union`)으로 다시
얹는다 — 양쪽이 파일 끝에 덧붙여도 충돌 마커 없이 둘 다 남고, 같은 줄을 양쪽이 넣었으면 하나만 남는다. 결과적으로 VM 파일은 "새
upstream + 아직 커밋 안 된 VM 기록"이 되어 에이전트가 계속 이어 쓸 수 있다. 로컬 내용은 어떤 경우에도 버려지지 않는다: pull이 다른
이유로 실패하면 백업에서 원래 내용으로 복원하고, 병합 자체가 실패하면 배포는 계속하되 백업 위치와 함께 텔레그램으로 알린다.
겹치지 않는 경우(원격이 이 파일을 안 바꾸거나 VM 쪽이 깨끗함)는 아무것도 하지 않는다. **다른 파일**의 로컬 수정이 pull을 막는
경우는 여전히 위 원칙대로 즉시 포기하고 알린다. 참고: 이렇게 VM에만 있는 기록은 누군가 커밋·푸시하기 전까지 GitHub에는 없다(백업은 매일 받는다 — 15번).
**대상 파일은 `deploy/progress_reconcile.sh`의 `RECONCILE_FILES`** — 2026-09-21부터 `PROGRESS.md`와 `docs/reports/README.md` 둘이다(VM 리서치 에이전트가 리포트 색인을 파일 안 여러 곳에 미커밋으로
끼워 넣고 있었다). 파일을 더 넣으려면 "에이전트가 덧붙이는 기록/색인이라 union 병합이 안전한가"를 먼저 확인할 것.

**재시작 뒤 상태 확인** (2026-09-21, `deploy/post_deploy_check.sh`): 예전엔 `systemctl restart` 직후 곧바로 "[자동배포] 성공"을 알렸다. 이제는 재시작한 서비스가 실제로 active가 될 때까지
(기본 90초) 기다리고, 헬스 엔드포인트가 있는 것(Streamlit `/_stcore/health`, 허브 `/`)은 응답을 확인하고, 잠깐(8초) 뒤 다시 확인해 "떴다가 곧바로 죽는" 재시작 루프까지 잡은 다음에야 성공을 알린다.
하나라도 비정상이면 "[자동배포] 배포는 됐지만 재시작 후 서비스가 정상이 아님"과 서비스 이름을 텔레그램으로 알린다(테스트는 통과했는데 실제 기동에서만 죽는 경우를 위한 것). 자동 롤백은 하지 않는다 —
비파괴 원칙상 되돌리는 커밋을 올리면 자동으로 다시 배포된다.

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
- `kind="link"` (예: 퀀트 대시보드, 브라우저 코드 스페이스): 슬롯의 `url`(HTTPS 하위 도메인)을 새 탭으로
  연다 — 14번 게이트웨이 구성. 허브 자체도 이제 `https://<도메인>/`에서 로그인 뒤에 뜬다.
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

**허브 카드**: 허브의 "브라우저 코드 스페이스" 카드(`kind="link"`)는 아래 게이트웨이의 `code.` 주소로 바로
연결된다(`hub/apps_registry.py`의 `url`). DuckDNS 장애나 공인 IP 변경으로 주소가 안 열릴 때는 위 SSH 터널이 대안이다.

### 도메인 게이트웨이 — 하나의 도메인 아래 허브 + 하위 앱 (2026-09-20 결정, 무료 DuckDNS + Let's Encrypt)

SSH 터널은 Codespace를 먼저 열어야 해서 불편하므로, 아무 기기 브라우저에서 주소 + 로그인만으로 들어오게 한다.
포트를 그대로 여는 게 아니라(평문 HTTP + 비밀번호 하나로 노출하는 셈이라 안 함) **nginx가 443에서 TLS를 끝내고
각 앱을 `127.0.0.1`로 프록시**한다 — 앱들은 계속 로컬 전용이다. 현재 운영 중인 주소는 `hessejeong.duckdns.org`.

| 주소 | 가는 곳 | 로그인 |
| --- | --- | --- |
| `https://hessejeong.duckdns.org/` | 관제 허브 (`127.0.0.1:8000`) | nginx 아이디/비밀번호 |
| `https://code.hessejeong.duckdns.org/` | code-server (`127.0.0.1:8080`) | code-server 자체 비밀번호 |
| `https://app.hessejeong.duckdns.org/` | Streamlit 대시보드 (`127.0.0.1:8501`) | nginx 아이디/비밀번호 |

(2026-09-21부터 Streamlit 유닛 자체도 `--server.address=127.0.0.1`로 떠서, 방화벽 규칙이 어떻게 되든 nginx 없이는 밖에서 닿지 않는다. 쓰지 않는 `rpcbind`(111번)도 꺼뒀다.)

DuckDNS는 `code.`·`app.` 같은 하위 이름도 자동으로 같은 IP로 풀어주므로 따로 등록할 게 없다. 세 이름은 **인증서
한 장**을 공유한다. 등록되지 않은 이름이나 IP로 들어온 HTTPS는 TLS 핸드셰이크 단계에서 거절하고(`ssl_reject_handshake`),
`http://<IP>/`는 기본 도메인으로 301 리다이렉트한다(더 이상 로그인 없는 허브를 IP로 보여주지 않는다).
새 하위 앱을 붙이려면 `deploy/setup_gateway.sh`에 server 블록 하나와 `hub/apps_registry.py`의 슬롯 하나를 추가하고
인증서에 이름을 더한다(스크립트가 `--expand`로 처리).

**처음 설치하는 순서**

1. https://www.duckdns.org 에서 GitHub 등으로 로그인해 무료 서브도메인을 만들고, IP에 이 VM의 공인 IP를 넣는다.
2. Oracle 콘솔 VCN Security List에 `TCP / 443 / 0.0.0.0/0` Ingress 규칙 추가 (80은 이미 열려 있음).
3. **허브/앱 로그인 비밀번호 파일을 사람이 직접 만든다** — 비밀번호가 대화나 로그에 남지 않도록 대화형으로 입력하며,
   이 파일이 없으면 스크립트는 허브/앱을 로그인 없이 공개하지 않고 멈춘다. 로컬 터미널(VS Code 하단 Terminal 패널)에서:
   ```bash
   ssh -t quant-vm 'read -rp "로그인 아이디: " U; read -rsp "비밀번호: " P; echo; printf "%s:%s\n" "$U" "$(printf %s "$P" | openssl passwd -apr1 -stdin)" | sudo tee /etc/nginx/.htpasswd-quant >/dev/null && sudo chown root:www-data /etc/nginx/.htpasswd-quant && sudo chmod 640 /etc/nginx/.htpasswd-quant && echo 저장됨'
   ```
   비밀번호는 숫자 4자리 같은 쉬운 것 대신 단어 3~4개를 하이픈으로 이은 것을 권장한다(공백·`"`·`\`는 피할 것).
   허브와 Streamlit(포트폴리오 데이터)을 지키는 비밀번호이고, 로그인 시도 제한(rate limit)은 없다.
4. VM에서: `sudo bash /opt/quant/deploy/setup_gateway.sh <이름>.duckdns.org [이메일]`
   — DNS 확인 → certbot 설치·인증서 발급(자동 갱신) → nginx 게이트웨이 설치 → 443 허용(iptables + ufw) → 확인.
   nginx 단계에서 실패하면 건드린 사이트 파일을 되돌리고 멈춘다. 여러 번 돌려도 안전하다(인증서는 만료 임박 때만 재발급).
5. `https://<이름>.duckdns.org/` 접속 → 아이디/비밀번호 → 허브. 카드에서 각 앱으로 이동한다.

**로그인 계정 바꾸기/추가**: 위 3번 명령을 다시 실행하면 파일이 통째로 새로 써진다(여러 계정을 두려면 `sudo tee -a`로
줄을 덧붙인다). nginx 재시작은 필요 없다.

**예전 직접 접속 경로 (닫힘, 2026-09-20)**: 평문 `http://<IP>:8501`은 로그인 없이 Streamlit이 열리는 옛 경로라 iptables의
8501 ACCEPT 규칙과 `ufw allow 8501/tcp`를 지워 닫았다(밖에서 연결 안 됨 확인). 다시 열지 말 것 — 새로 앱을 붙일 때도
포트를 직접 열지 말고 게이트웨이에 서버 블록을 추가한다. Oracle Security List에 남아 있는 8501·8080 Ingress 규칙은 이제
아무 효과가 없으니(OS 방화벽이 막음) 콘솔에서 지워도 된다 — 지우면 방화벽 한 겹이 더 생기는 셈이다.

**코드 스페이스 비밀번호를 외울 수 있는 것으로 바꾸기**: code-server 비밀번호는 처음에 자동 생성된 24자 랜덤 문자열이라
외울 수 없다. 사람이 직접 아래를 실행하면(비밀번호는 화면에 안 보이게 두 번 입력, 명령줄·대화·로그에 남지 않음) 원하는
것으로 바꾸고 재시작한 뒤 실제 로그인이 되는지 확인하며, 안 되면 예전 설정으로 되돌린다:
```bash
ssh -t quant-vm 'sudo bash /opt/quant/deploy/set_code_server_password.sh'
```
12자 이상, 영문/숫자/기호(`!` `@` `#` 등)를 받는다 — 공백, 작은따옴표(`'`), 한글 같은 ASCII 아닌 글자는 안 된다(거절될 때는
어떤 *종류*의 글자가 문제인지만 알려주고 글자 자체는 출력하지 않는다; 한/영 키가 한글 상태로 영문을 치면 한글이 들어가 거절된다).
단어 3~4개를 하이픈으로 이은 것(예: `blue-moon-cat-42` 형태)이 외우기 쉽고 충분히 길다 — 이 비밀번호 하나가 곧 VM 셸이라 4자리 숫자 같은 건 일부러 거절한다. 브라우저/휴대폰의 "비밀번호 저장"을
누르면 다음부터는 아예 안 쳐도 된다. 허브(기본 도메인)와 `app.`은 nginx 아이디/비밀번호(위 3번 명령), `code.`는 code-server
비밀번호로 서로 다른 로그인이고, 브라우저는 주소(호스트)마다 따로 기억한다. 이 스크립트는 설정 파일 권한을 항상 `640`으로
맞춘다(`quant` 계정의 암호화 비밀 백업이 읽어야 해서 — 15번).

이제 비밀번호가 평문으로 오가지는 않지만, code-server 비밀번호 하나가 곧 VM 셸이다 — 강한 비밀번호(현재 24자)를
유지하고 쉬운 것으로 바꾸지 말 것(code-server가 로그인 시도를 분당 몇 회로 제한하긴 한다). DuckDNS는 무료·후원 기반
서비스라 드물게 불안정할 수 있고, VM 공인 IP가 바뀌면(인스턴스 중지 후 재시작 등 — 예약 IP가 아니라면) DuckDNS 화면에서
IP를 직접 고쳐야 한다. 그때는 위 SSH 터널이 대안이다. 인증서는 certbot 타이머가 자동 갱신한다
(`systemctl list-timers | grep certbot`).

**알아둘 것 — 이 VM의 방화벽은 지금 상태와 재부팅 후 상태가 다르다** (2026-09-20 확인):
- **지금(부팅 후 계속 켜져 있는 동안)**: `/etc/iptables/rules.v4`에서 온 Oracle 기본 `REJECT`가 INPUT 체인에서
  ufw 체인보다 **앞에** 있어서, `ufw allow`만 하면 패킷이 REJECT에서 끝나 ufw 체인에 도달하지 못한다
  (8080으로 확인 — Oracle VCN Security List는 통과하는데 VM 안에서 거절됨). 22/80/443은 그 REJECT
  **앞에** 직접 `iptables -I INPUT ... -j ACCEPT`로 넣어둔 것이라 통한다.
- **재부팅 후**: `iptables-persistent`/`netfilter-persistent` 패키지가 **제거된 상태(dpkg `rc`)**라 부팅 때
  `rules.v4`를 복원하는 장치가 없다. 그러면 수동으로 넣은 iptables ACCEPT와 REJECT가 모두 사라지고
  **ufw 규칙이 방화벽 역할**을 한다(ufw는 부팅 시 자동 활성화). 즉 새 포트를 공개하려면 **iptables ACCEPT(즉시
  적용) + `ufw allow`(재부팅 후 유지) 둘 다** 넣어야 한다 — `setup_gateway.sh`가 443에 대해 그렇게 한다.
- 기존 22/80/443의 iptables 규칙은 재부팅 후 사라지지만 ufw에도 같은 규칙이 있어 접속은 유지된다.

## 15. VM 백업 — 디스크 한 대에만 있는 것들을 밖으로 (2026-09-21)

**왜**: `data/quant.db`(포트폴리오/관심종목/전략 결과), 리서치 에이전트가 만든 미커밋 산출물(`analysis/`, `docs/experiment_validation/` …), 에이전트가
`PROGRESS.md`에 미커밋으로 덧붙인 기록은 이 VM 디스크에만 있다. 예전엔 백업이 전혀 없어서 디스크가 사라지면 전부 사라지는 구조였다.

**구성**: `deploy/backup_vm.py`(stdlib만, `quant` 계정) + `quant-backup.timer`(매일 한국시간 06:30). 설치는 `sudo bash /opt/quant/deploy/setup_backup.sh`.
- **무엇을**: (1) `data/quant.db`를 sqlite 온라인 백업 API로(쓰는 도중에도 일관된 사본 + 무결성 검사), (2) git 기준 *커밋 안 된* 파일(미추적+수정됨) 중
  **허용 목록**(`analysis/`, `analysis.root_backup_*`, `docs/`, `deploy/research_agents/`, `.experiment-control/`, `PROGRESS.md`, `RESUME_NOTE.md`,
  `data/process_toggles.json`) 아래의 것만. 이미 GitHub에 있는 파일은 복사하지 않는다.
- **절대 안 들어가는 것**: 점(`.`) 폴더 전부(`.claude`, `.codex`, `.ssh`, `.codex-telegram-runtime`, `.config`, `.env` — 인증 정보가 든다)는 허용 목록에 없어서 구조적으로
  제외된다. 허용 폴더 안이라도 비밀처럼 생긴 파일명(`.env*`, `*.pem`, `id_*`, `auth.json`, `credentials*`)이나 내용(개인 키, `ghp_`/`sk-ant-`/`AKIA` 등 토큰,
  텔레그램 봇 토큰 모양)이 있으면 **격리**(백업 제외 + 텔레그램 알림). 90MB 넘는 파일(GitHub 한도)과 `.experiment-control/checkpoints/`(수백 MB tar.gz)는 건너뛴다.
- **어디에**: `/opt/quant-backup/repo` — 로컬 git 저장소라 바뀐 것만 커밋되고 버전 이력이 남는다(델타 압축). 같은 디스크라 실수로 지움/손상은 막지만 **디스크 소실은
  못 막는다** — 그래서 `/opt/quant-backup/remote`에 **비공개** 저장소 URL이 있으면 매일 거기로도 push한다(전용 배포 키 `/opt/quant-backup/ssh/id_ed25519`).
  **이 Quant 저장소는 공개라서 백업을 여기 올리면 안 된다** — 반드시 별도의 비공개 저장소여야 한다.
- **상태**: `/opt/quant-backup/status.json` → 오늘의 브리핑 "운영 상태"와 워치독이 읽는다. 백업 실패/36시간 넘게 성공 없음/원격 push 3일 넘게 실패/비밀 의심 격리는
  텔레그램으로 알린다(원격 미설정은 알림 없이 브리핑에만 표시).

- **"써졌다"와 "복구된다"는 다르다 — 검증과 복구 리허설** (2026-09-21): 매 실행마다 저장본 전체를 `MANIFEST.json`의 sha256로 다시 검증하고(파일 없음/내용 불일치), DB 사본의 무결성을 확인하며,
  `git fsck`도 돈다. 검증이 실패하면 그 실행은 실패로 치고 **밖으로 올리지도 않는다**. 원격 push 뒤에는 원격 main의 HEAD가 로컬과 같은지 확인한다. 또 **7일에 한 번 복구 리허설**을 한다:
  백업 저장소(원격이 있으면 원격, 없으면 로컬)를 임시 폴더에 새로 클론해 같은 검증을 통과하는지 본다 — 디스크가 사라진 뒤 실제로 하게 될 경로를 미리 밟아보는 것이다. 결과는 `status.json`과
  브리핑에 나오고, 실패하면 텔레그램으로 알린다(원격이 있는데 10일 넘게 리허설이 없으면 브리핑에 경고).

**비공개 원격 연결 (사람이 한 번, GitHub 웹에서 약 2분)**:
1. GitHub에서 **Private** 저장소를 만든다(예: `quant-vm-backup`, README 없이 빈 저장소).
2. 그 저장소 Settings → Deploy keys → Add deploy key → 제목 `quant-vm`, 키는 VM에서 `cat /opt/quant-backup/ssh/id_ed25519.pub`(공개 키라 비밀 아님)를 붙여넣고
   **Allow write access** 체크.
3. VM에서: `echo 'git@github.com:<계정>/quant-vm-backup.git' | sudo -u quant tee /opt/quant-backup/remote`
4. 바로 확인: `sudo -u quant python3 /opt/quant/deploy/backup_vm.py` → `비공개 저장소 push 성공`이 나오면 끝.

**복구** (새 VM 또는 데이터 손상 시):
```bash
# 새 VM이면 먼저 setup_backup.sh로 배포 키를 만들고 그 공개 키를 백업 저장소 Deploy keys에 등록(읽기 권한이면 충분)
git clone git@github.com:<계정>/quant-vm-backup.git /tmp/restore
sudo systemctl stop quant-scheduler quant-streamlit
sudo -u quant cp /tmp/restore/db/quant.db /opt/quant/data/quant.db          # DB (integrity_check 통과한 사본)
sudo -u quant rsync -a --exclude PROGRESS.md /tmp/restore/files/ /opt/quant/  # 연구 산출물(미커밋이던 것들)
# PROGRESS.md는 덮어쓰지 말고 차이만 옮긴다: diff /tmp/restore/files/PROGRESS.md /opt/quant/PROGRESS.md
sudo systemctl start quant-scheduler quant-streamlit
```
이력이 필요하면 `git -C /tmp/restore log`, 특정 날짜 버전은 `git -C /tmp/restore show <커밋>:db/quant.db`. `MANIFEST.json`에 파일별 크기/sha256이 있다.

**비밀(nginx 로그인·code-server 비밀번호·`.env`·텔레그램 토큰·Claude/Codex 로그인) — 암호화 백업 (선택, opt-in, 2026-09-22)**:
기본은 위 "절대 안 들어가는 것"대로 완전히 제외다. `/opt/quant-backup/secrets_passphrase` 파일(사람이 대화형으로 직접 만듦, 아래)이 있을 때만
`deploy/backup_vm.py`가 매 실행마다 이 다섯 가지를 파일별로 `openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt`로 암호화해 `repo/secrets/<라벨>.enc`로
함께 백업한다(암호화 직후 그 자리에서 복호화해 원문과 일치하는지 확인 — 실패하면 그 회차 전체를 실패로 치고 밖으로 올리지 않는다). 이 VM에 없는 항목(예: Codex 로그인)은
조용히 건너뛴다. **있는데 못 읽는 것**(권한 문제)도 그 라벨만 건너뛴다 — 2026-09-22에 실제로 nginx 로그인 파일(`root:www-data 640`)과
code-server 설정(`ubuntu:ubuntu 640`, `/home/ubuntu` 자체도 750)이 `quant` 계정 권한 밖이라 이 상황을 겪었다. `setup_backup.sh`가
`quant`를 `www-data`·`ubuntu` 그룹에 넣어 이걸 해결하고(둘 다 idempotent), 이후 비밀번호를 바꿔도 nginx 쪽은 항상 같은 소유권으로
다시 만들어지고 code-server 쪽은 `set_code_server_password.sh`가 매번 `640`을 강제해 계속 읽을 수 있다. 브리핑에 "권한 문제로
못 읽은 비밀 파일"이 보이면 이 두 그룹 소속을 먼저 확인할 것. `secrets_passphrase` 파일 자체는 `/opt/quant-backup`(백업 *대상*인
`/opt/quant` 밖)에만 있어서 수집 대상에 절대 섞이지 않고, 백업 저장소(비공개 원격 포함)에도 절대 올라가지 않는다.

**여기서 지켜지는 것과 안 지켜지는 것을 정확히 알아야 한다**: passphrase가 VM에만 있으므로 "백업 저장소(비공개 원격)가 뚫려도 이 비밀들은 못 연다"는 지켜진다.
하지만 "VM 디스크가 통째로 사라지는 경우"까지 막으려면 **같은 passphrase를 사람이 따로(비밀번호 관리자 등에) 보관해야 한다** — VM과 함께 이 파일도 사라지기
때문이다. **잊어버리면 그 뒤로는 아무도(나도) 복구할 수 없다.**

설정 (사람이 한 번, VS Code Terminal 패널):
```bash
ssh -t quant-vm 'sudo bash /opt/quant/deploy/set_backup_passphrase.sh'
```
20자 이상이면 공백·한글 등 제한이 거의 없다(셸에 끼워 넣지 않고 파일로만 저장하므로). 단어 4~5개를 띄어 쓴 문장 형태를 권장. 저장 직후 그 passphrase로
실제 암복호화 왕복까지 확인한 뒤에만 저장한다. 바로 확인: `sudo -u quant python3 /opt/quant/deploy/backup_vm.py` → 요약에 "비밀 백업 N개"가 뜬다.

복구할 때(위 절차로 저장소를 받은 뒤):
```bash
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass pass:'<passphrase>' -in /tmp/restore/secrets/app_env.enc -out .env
```
각 `<라벨>.enc`를 원래 위치(`nginx_htpasswd`→`/etc/nginx/.htpasswd-quant`, `code_server_config`→code-server의 `config.yaml`, `app_env`→`.env`,
`telegram_env`→`.codex-telegram-runtime/telegram.env`, `claude_credentials`→`.claude/.credentials.json`, `codex_auth`→`.codex/auth.json`)에 같은 방식으로 복원한다.

## 16. 밤사이 작업 관측과 워치독 — "조용한 실패"를 막는 장치 (2026-09-21)

**왜**: 야간 전략 튜닝이 한 번도 안 돌았는데도 아무 데서도 드러나지 않았던 적이 있다. 사용자가 폰으로만 운영하므로, 저널을 뒤져야만 보이는 실패는 없는 것과 같다.

- **실행 이력**(`scheduler_job_runs` 테이블): `scheduler/run_scheduler.py`가 APScheduler 이벤트 리스너(`core/job_health.py`)를 달아서, 잡 하나가 끝날 때마다
  `ok`/`error`/`missed`를 한 줄씩 기록한다(90일 보관). 잡 함수는 하나도 안 고쳤다. `core/job_schedule.py`가 16개 잡의 스케줄 표이고, `tests/test_job_health.py`가
  `main()`의 실제 등록과 표가 일치하는지 검증하므로 잡을 추가/변경하면 표도 같이 고쳐야 테스트가 통과한다(표가 조용히 낡을 수 없다).
- **판정**(`compute_job_health`): 스케줄 표로 "지금쯤 마지막으로 돌았어야 할 시각"을 계산해 그 뒤의 기록과 맞춘다 → `ok` / `error` / `missed` / `overdue`(예정 45분 뒤에도
  기록 없음) / `pending`(유예 중) / `disabled`(꺼진 잡은 문제 아님) / `no-history`(이력 추적 시작 전의 예정 시각 — 배포 직후 오경보 방지).
- **오늘의 브리핑**(00:25 KST)에 "운영 상태" 섹션이 생겼다: 문제가 있으면 맨 위 + 상태 문구가 빨강, 없으면 맨 아래에 한 줄 요약 + VM 백업 상태.
- **워치독**(`deploy/watchdog.py`, `quant-watchdog.timer`, 매일 한국시간 09:05): 스케줄러/앱과 **독립적으로**(stdlib, venv 불필요) 돈다 — 브리핑도 스케줄러 안의 잡이라 스케줄러가
  죽으면 함께 안 오기 때문이다. 확인: 최근 26시간에 잡 기록이 있는가(있던 적이 있는데 없으면 스케줄러 정지) / error·missed 잡 / 최신 브리핑이 26시간 안인가 / 백업 상태.
  **문제가 있을 때만** 텔레그램으로 알리고 조용히 끝난다. 수동 실행: `python3 /opt/quant/deploy/watchdog.py --dry-run`.
- **소프트 실패 보고** (2026-09-21): 잡 16개 중 예외를 내부에서 삼키고 정상 반환하는 것은 뉴스 다이제스트·FRED 예열·(꺼진) 야간 튜닝 셋이라, 실패해도 APScheduler에는 `ok`로 보인다. 앞의 둘은
  실패 지점에서 `report_job_failure()`로 `status="failed"` 행을 직접 남기고(FRED는 지표를 하나도 못 받았을 때만), 판정은 그 잡의 이후 `ok`보다 이 실패를 우선한다. 워치독도 `failed`를 오류로 센다.
- **재부팅 방치 알림** (2026-09-21): 워치독이 `/var/run/reboot-required`(보통 커널 보안 업데이트)가 **14일 넘게** 방치되면 텔레그램으로 알린다. 자동으로 재부팅하지는 않는다 — 부팅이 잘못되면
  사람이 Oracle 콘솔에서 되살려야 하기 때문이다. (도입 시점에 이미 28일째 방치 중이었음.)
- **주간 생존 신호** (2026-09-21): 문제가 없어도 **일요일(KST)** 워치독이 요약 한 통(최근 7일 작업 기록 수, 백업 상태)을 보낸다. 워치독/텔레그램 자체가 죽으면 "이상 없음"과 "알림이 안 옴"을 구분할 수
  없기 때문이다 — 일요일에 이 메시지가 안 오면 그것이 이상 신호다. 문제가 있는 날은 문제 알림만 간다.
- **한계**: "돌았는가"를 보장할 뿐 "결과가 좋았는가"는 아니다 — 위 두 잡 말고 잡이 내부에서 예외를 삼키는 경우는 `ok`로 남는다(결과 신선도는 `core/data_integrity.py`가 따로 본다).

## 17. 외부 감시 (`.github/workflows/uptime.yml`) (2026-09-21)

VM 안의 헬스체크(`quant-vm-health`)는 VM이 죽으면 함께 죽어서 알릴 수 없다. 이 워크플로가 **VM 밖(GitHub 서버)에서 30분마다** 확인한다: 세 주소가 DNS로 이 VM의 IP를
가리키는지, 기대한 응답인지(허브/앱 401, 코드 스페이스 302), 인증서 남은 기간이 14일 이상인지, 그리고 **닫아둔 포트(8501/8080/8000)가 밖에서 응답하지 않는지**(보안 회귀).
하나라도 어긋나면 워크플로가 실패로 표시되고 GitHub이 이메일/앱 알림을 보낸다. 텔레그램으로도 받으려면 저장소 시크릿에 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`를 추가하면
된다(없으면 그 단계는 건너뜀). 이 저장소는 공개라 Actions 분 제한이 없다. **공인 IP가 예약(Reserved) IP가 아니면** 인스턴스를 중지했다 켤 때 IP가 바뀌어 모든 주소가 깨진다 —
Oracle 콘솔 Compute → Instance → Attached VNICs → IPv4 addresses에서 확인하고, Ephemeral이면 Reserved로 바꾸는 것을 권한다(무료, 붙어 있는 동안). IP를 바꾸면 워크플로의
`EXPECTED_IP`도 같이 고쳐야 한다.

