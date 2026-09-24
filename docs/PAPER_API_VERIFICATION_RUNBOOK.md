# Alpaca paper API 검증 런북 (사람이 VM에서 실행)

## 자동 실행 (2026-09-24)

**사람이 아무것도 안 해도 읽기 전용 검증은 VM 스케줄러가 돌린다.** 이 절의 자동 경로는 구현·단위 테스트(mock)까지만 끝났고, 배포 후 실제 VM 실행 결과는 아직 없다.

- **무엇이 도는가:** 스케줄러 잡 `alpaca_verification_bootstrap`(매일 00:40 KST). 최근 7일 안에 전체 PASS 결과가 없을 때만 읽기 전용 검증 4개(멱등성 스크립트의 기본 읽기 전용 모드, 기업행동, 가격 교차검증, 계좌 스키마)를 순서대로 실행한다. PASS 가 있으면 조용히 건너뛴다. 키(`ALPACA_PAPER_API_KEY`/`ALPACA_PAPER_API_SECRET`)는 VM `/opt/quant/.env` 의 환경변수에서만 읽고 값은 파일·텔레그램·로그 어디에도 쓰지 않는다. 키가 없으면 "키 없음" 알림만 보내고 끝난다.
- **자동으로 하지 않는 것:** 주문을 내는 `--write` 경로는 절대 자동 실행하지 않는다. 그래서 자동 PASS 는 연결·인증·계정 필드·미존재 ID 404 등 **읽기 전용 범위**만 뜻한다. 중복 POST 422·주문 후 조회·취소 의미는 여전히 미검증이며, 이 절 아래 기존 절차대로 사람이 `--write` 로 실행해야 한다.
- **결과 확인(폰으로):** 텔레그램에 요약 1건이 온다(`[Alpaca paper 검증] 전체 PASS (4/4 PASS)` 형태, 실패 시 어느 검증의 어느 단계가 가정과 달랐는지 한 줄씩). 같은 실패는 3일 안에 반복 알리지 않는다. 상세는 VM 의 `data/verification/alpaca_YYYYMMDD_HHMM.json`(UTC 기준 파일명).
- **판정 의미:** PASS = 가정과 일치, FAIL = 응답을 받았으나 코드 가정과 다름(해당 모듈 파싱 지점 수정 필요), UNEXPECTED = 판단 불가(인증 거부·네트워크·구독 등급 한계 등).
- **끄기:** 텔레그램 `/processes` 에서 `alpaca_verification_bootstrap` 을 끈다.
- **관측 전용 잡(같은 시기 추가):** `cost_calibration_refresh`(00:42), `variant_shadow_record`(00:44), `strategy_research_report`(일 00:50)는 검증과 무관한 연구용 관측 잡이며 주문 경로에 연결되어 있지 않다.


상태: 도구 구현 완료, **실제 paper API 대상 실행은 아직 한 번도 하지 않았다.** 아래 검증 도구는 requests mock(가짜 서버) 단위 테스트만 통과했다. 이 문서의 VM 명령도 이 저장소 환경(Codespace)에서는 실행해 볼 수 없어 **VM에서 처음 실행할 때 확인이 필요한 절차**다. 실행 결과가 나오기 전까지 `client_order_id` 멱등 주문 경로는 "가정 + mock 검증" 상태로 취급한다.

## 1. 무엇을 검증하나

`core/paper_execution.py`의 멱등 주문 경로는 Alpaca가 다음과 같이 답한다고 **가정**한다. 도구 `scripts/verify_alpaca_paper_idempotency.py`가 실제 응답 코드를 기록하고 가정과 비교해 PASS / FAIL / UNEXPECTED로 판정한다.

| 가정 | 코드에서 의존하는 곳 | 도구 단계 |
|---|---|---|
| 존재하지 않는 `client_order_id` 조회 → HTTP 404 | `order_by_client_id`가 404일 때만 `None` 반환 | R3, R4 |
| 계정 응답에 `id`(또는 `account_number`)·`equity`·`trading_blocked`·`account_blocked` 있음 | `submit_plan`, `champion_paper_trade.py` | R2 |
| 같은 `client_order_id`로 재제출 → HTTP 422 | `submit_plan`이 422를 "애매한 실패"로 보고 조회로 대조, 그 외 4xx는 `rejected` 처리 | W2, W2b |
| 방금 낸 주문이 `client_order_id`로 조회됨 | 재시도 때 중복 주문을 막는 유일한 장치 | W3 |
| 취소된 주문(체결 0) → `canceled` → 코드 분류 `rejected`(종결) | 회차 종료 판정 `_is_terminal` | W4, W5 |

읽기 전용 실행(기본)은 R1~R4만 확인한다. **재제출 422·조회·취소 의미는 `--write`를 줘야 검증된다.** 읽기 전용이 PASS여도 리포트의 `idempotency_verified`는 `false`다.

이 도구가 검증하지 **않는** 것: 시장가·`notional` 주문의 체결, 부분체결 응답, 거절 사유별 응답 코드, rate limit 동작, 장중 실제 체결. PASS여도 "주문 경로가 운영 가능"이라는 뜻이 아니라 위 가정 5개가 실제 API와 일치했다는 뜻이다.

## 2. 필요한 환경변수 (이름만 — 값은 어디에도 적지 않는다)

| 이름 | 용도 |
|---|---|
| `ALPACA_PAPER_API_KEY` | paper 계정 API 키 ID |
| `ALPACA_PAPER_API_SECRET` | paper 계정 API 시크릿 |
| `QUANT_PAPER_RUN_DB` | (선택) 실행 회차 DB 경로. 없으면 `data/paper_runs.db` |

도구는 이 두 이름을 **환경변수에서만** 읽는다(`.env` 파일을 직접 파싱하지 않는다). 값은 출력·저장하지 않고, 응답 본문에 우연히 섞여 들어와도 리포트에서 `[REDACTED]`로 가린다. 접속 주소는 코드에 고정된 `https://paper-api.alpaca.markets` 하나뿐이며 실계좌 주소로 바꾸는 옵션은 없다. paper 키 발급은 Alpaca 대시보드의 Paper Trading > API Keys에서 하며, 시크릿은 발급 화면에서 한 번만 보이므로 발급 즉시 `/opt/quant/.env`에 넣고 다른 곳(채팅·문서·커밋)에 붙여넣지 않는다.

## 3. 실행 전 확인사항

### 3-1. VM에 키가 들어 있는지 확인 (값은 숨기고 이름과 길이만)

VM의 환경변수 파일은 `/opt/quant/.env`다(소유자 `quant`, 권한 600이라 `sudo`가 필요하다).

```bash
sudo awk -F= '/^ALPACA_PAPER_API_/{print $1, length($2)}' /opt/quant/.env
```

기대 출력은 정확히 두 줄이다.

```
ALPACA_PAPER_API_KEY <길이>
ALPACA_PAPER_API_SECRET <길이>
```

읽는 법:

| 출력 | 의미 | 조치 |
|---|---|---|
| 아무것도 안 나옴 | `.env`에 키가 없음 | 값을 `.env`에 추가(3-2) |
| 한 이름만 나옴 | 나머지 하나 누락 | 누락된 줄 추가 |
| 같은 이름이 두 번 이상 | **중복 정의** | 3-3으로 정리 |
| 길이가 발급 화면의 글자 수보다 1 큼 | 줄 끝에 Windows 줄바꿈(CR) 섞임 | 3-3의 줄바꿈 제거 |
| 길이가 2 큼 | 값을 따옴표로 감쌈 | 따옴표 제거 |
| 길이가 0 | `NAME=` 뒤가 비어 있음 | 값 채움 |

Alpaca 키 ID는 보통 20자, 시크릿은 보통 40자다(발급 형식 기준이며 다르면 발급 화면과 대조한다). 길이만으로는 값이 맞는지 알 수 없다. 최종 판단은 도구의 R1·R2 단계(인증 성공 여부)가 한다. 값의 앞 두 글자만 확인하려면(paper 키 ID는 보통 `PK`로 시작) 다음을 쓸 수 있다.

```bash
sudo awk -F= '/^ALPACA_PAPER_API_KEY=/{print substr($2,1,2)}' /opt/quant/.env
```

이름·행 번호까지 보려면(주석 처리된 줄, `export ` 접두사가 붙은 줄까지 함께 드러난다):

```bash
sudo awk -F= '/ALPACA_PAPER_API_/{print NR, $1, length($2)}' /opt/quant/.env
```

`#ALPACA_...`처럼 주석이면 무시되고, `export ALPACA_...`처럼 `export`가 붙은 줄은 systemd `EnvironmentFile`이 변수로 읽지 못하므로 그 줄은 `export `를 지워야 한다.

### 3-2. 키 추가

```bash
sudo nano /opt/quant/.env        # 아래 두 줄을 추가 (값은 발급 화면에서 복사, 따옴표·공백 없이)
# ALPACA_PAPER_API_KEY=...
# ALPACA_PAPER_API_SECRET=...
ls -l /opt/quant/.env            # 소유자 quant, 권한 -rw------- 유지 확인
```

권한이 바뀌었으면 `sudo chown quant:quant /opt/quant/.env && sudo chmod 600 /opt/quant/.env`로 되돌린다(`deploy/setup_vm.sh`와 같은 설정).

### 3-3. `.env`에 같은 이름이 중복될 때 정리

systemd `EnvironmentFile`도 셸 `source`도 **같은 이름이 여러 번 나오면 마지막 줄이 이긴다.** 그래서 앞쪽에 오래된(틀린) 값이 남아 있어도 겉보기엔 동작하고, 나중에 줄 순서가 바뀌면 조용히 인증이 깨진다. 한 이름에 한 줄만 남긴다.

1. 백업을 **저장소 밖**에 만든다(`.env.bak` 같은 파일을 `/opt/quant` 안에 두면 git 작업트리에 비밀 파일이 남는다).
   ```bash
   sudo install -m 600 -o root -g root /opt/quant/.env /root/quant.env.bak-$(date +%F)
   ```
2. 중복 위치를 확인한다(행 번호와 길이만 출력).
   ```bash
   sudo awk -F= '/ALPACA_PAPER_API_/{print NR, $1, length($2)}' /opt/quant/.env
   ```
3. 편집기로 열어 **가장 마지막 줄(현재 실제로 적용되는 값)만 남기고** 나머지를 지운다. 어느 쪽이 맞는지 모르면 두 줄을 모두 지우고 발급 화면에서 다시 복사해 한 줄씩 넣는 편이 안전하다.
   ```bash
   sudoedit /opt/quant/.env
   ```
4. 줄 끝 CR이 섞였으면 제거한다.
   ```bash
   sudo sed -i 's/\r$//' /opt/quant/.env
   ```
5. 다시 3-1의 첫 명령을 실행해 **각 이름이 정확히 한 번**, 길이가 기대값인지 확인한다. 권한도 확인한다(`ls -l /opt/quant/.env` → `quant quant`, `-rw-------`).
6. 백업 파일은 확인이 끝나면 `sudo shred -u /root/quant.env.bak-<날짜>`로 지운다(값이 남는 파일이므로).
7. 도구는 실행할 때마다 `.env`를 새로 읽는 프로세스라서 재시작이 필요 없다. 다만 `quant-scheduler`·`quant-streamlit` 서비스는 시작 시점의 값을 들고 있으므로, 이 서비스들이 Alpaca 키를 쓰는 경로가 생기면 그때는 `sudo systemctl restart`가 필요하다(저장소를 grep한 결과 `app/`·`scheduler/`는 `paper_execution`을 import하지 않고, `core/paper_execution.py`는 `scripts/champion_paper_trade.py`·`scripts/paper_run_admin.py`·`scripts/verify_alpaca_paper_idempotency.py` 세 CLI에서만 쓰인다. VM 위의 실제 서비스 상태는 확인하지 못했다).

### 3-4. 나머지 체크리스트

- [ ] 코드가 최신이다: `git -C /opt/quant log -1 --oneline`이 검증하려는 커밋인지, `scripts/verify_alpaca_paper_idempotency.py`가 있는지 확인.
- [ ] 이 도구와 다른 주문 경로가 동시에 돌지 않는다. 열린 회차가 없는지 확인: `sudo -u quant /opt/quant/.venv/bin/python /opt/quant/scripts/paper_run_admin.py list --status open` (비어 있어야 한다. 남아 있으면 먼저 그 회차를 정리한다 — 8절).
- [ ] 계정이 **paper**다(도구는 paper 주소만 호출하므로 실계좌 키를 넣으면 인증 실패로 끝난다. 그래도 실계좌 키를 `.env`에 넣지 않는다).
- [ ] `--write`는 읽기 전용 실행이 PASS일 때만 한다.
- [ ] 테스트 주문의 안전장치를 이해했다: SPY 1주, 지정가 **$1.00**(현재가보다 훨씬 낮아 체결될 수 없음), 주문 금액 상한 $25 초과 시 도구가 실행을 거부한다. `--symbol`/`--limit-price`를 바꿀 때는 지정가가 현재가보다 **크게** 낮은지 직접 확인한다.

## 4. 실행 절차

VM에서 서비스와 같은 방식으로 환경변수를 넣어 실행한다. `quant` 계정은 로그인 셸이 없으므로 `systemd-run`이 `EnvironmentFile`을 서비스와 똑같이 해석한다(`quant-scheduler.service`와 같은 `User`·`WorkingDirectory`·`EnvironmentFile`). 리포트 JSON은 표준출력으로 나오므로 셸 리다이렉트로 **`data/` 밖**(예: 홈 디렉터리)에 저장한다. 판정 요약은 표준오류에 사람이 읽는 형태로 출력된다.

**1단계: 읽기 전용 (주문 없음)**

```bash
sudo systemd-run --wait --collect --pipe -p User=quant -p WorkingDirectory=/opt/quant \
  -p EnvironmentFile=/opt/quant/.env \
  /opt/quant/.venv/bin/python scripts/verify_alpaca_paper_idempotency.py > ~/paper_verify_readonly.json
echo "exit=$?"
```

**2단계: 쓰기 포함 (1단계가 PASS일 때만 — paper 계정에 테스트 주문 1건을 냈다가 취소한다)**

```bash
sudo systemd-run --wait --collect --pipe -p User=quant -p WorkingDirectory=/opt/quant \
  -p EnvironmentFile=/opt/quant/.env \
  /opt/quant/.venv/bin/python scripts/verify_alpaca_paper_idempotency.py --write > ~/paper_verify_write.json
echo "exit=$?"
```

`systemd-run`이 없거나 `--pipe` 출력이 이상하면 대안(같은 결과, 단 셸이 `.env`를 해석하므로 값에 공백·특수문자가 있으면 다르게 읽힐 수 있다):

```bash
sudo -u quant bash -c 'set -a; . /opt/quant/.env; set +a; cd /opt/quant && .venv/bin/python scripts/verify_alpaca_paper_idempotency.py'
```

종료 코드: `0` PASS, `1` FAIL, `2` UNEXPECTED, `3` 실행 전 설정 오류(키 이름 누락, `--output`이 `data/` 아래, 지정가 상한 초과 등). 종료 코드 `3`의 오류 메시지는 누락된 **환경변수 이름**만 알려준다.

## 5. 결과 해석

리포트의 각 `steps[]`에는 `expected`(코드가 가정한 값), `actual_status`(실제 HTTP 코드), `verdict`, `note`가 있다.

| 판정 | 뜻 |
|---|---|
| PASS | 실제 응답이 코드의 가정과 일치 |
| FAIL | 응답은 분명히 왔는데 코드의 가정과 **다르다** → 코드·테스트 수정 필요 |
| UNEXPECTED | 판정 불가(인증·권한·rate limit·서버 오류·파라미터 거절) 또는 위험 신호(주문이 체결됨). `note`를 읽고 원인 제거 후 재실행 |
| SKIPPED | 앞 단계가 실패해 실행하지 않음(예: 첫 제출 실패 시 재제출 등은 안 함) |

전체 판정(`overall`)은 FAIL이 하나라도 있으면 FAIL, 아니면 UNEXPECTED가 하나라도 있으면 UNEXPECTED, 아니면 PASS다.

| 단계 | PASS 의미 | 대표 실패 해석 |
|---|---|---|
| R1 clock, R2 account | 인증과 계정 필드 OK | UNEXPECTED(401/403): 키가 틀렸거나 paper 키가 아님. R2 FAIL: 계정 응답에 코드가 읽는 필드가 없음 |
| R3 조회(미존재 ID) 404 | 미존재 ID → 404 | FAIL(200/422 등): `order_by_client_id`가 `None` 대신 예외·가짜 주문을 반환 → 중복 방지 붕괴 |
| R4 코드 경로 | 실제 `AlpacaPaperBroker.order_by_client_id`가 `None` 반환 | FAIL: 위와 같음 |
| W1 최초 제출 | 접수(`accepted`/`new` 등)되어 코드가 `open`으로 분류 | UNEXPECTED: 파라미터/가격/buying power 거절 → 재제출 단계는 실행하지 않음. **주문이 체결됐다면(`filled`)** 지정가를 훨씬 낮춰 재시도하고 paper 포지션을 정리 |
| W2 재제출 | **422** | FAIL(2xx): 브로커가 중복을 받아줌 → 조회 후 제출이 유일한 방어선. FAIL(409 등): `submit_plan`이 이 응답을 `rejected`로 기록해 실제로는 존재하는 주문을 무시함. UNEXPECTED(2xx인데 같은 주문 ID 반환): 브로커가 동일 주문을 재응답 — 코드에는 무해하지만 422 가정과 다름 |
| W2b 같은 ID 주문 개수 | 정확히 1건 | FAIL(2건 이상): **중복 주문이 실제로 생김** |
| W3 조회(제출 직후) | 200 + 같은 주문, `open` | FAIL(404): 방금 낸 주문이 안 보임 → 멱등 보장 불가 |
| W4 취소 | 204 | UNEXPECTED: 취소 거절 — 이미 종결/체결됐을 수 있음 |
| W5 취소 확인 | `canceled` → 코드 분류 `rejected`(종결) | FAIL: 코드 분류가 취소를 종결로 보지 않아 회차가 영영 안 닫힘. UNEXPECTED(`pending_cancel` 지속): 대시보드에서 최종 상태 확인 |

리포트에는 이 밖에 다음이 있다.
- `verified_scope`, `idempotency_verified`: 읽기 전용이면 `false`(재제출·취소 미검증).
- `status_mapping`, `unmapped_statuses`: Alpaca 문서상 주문 상태 17종을 `classify_order_state`가 어떻게 분류하는지(오프라인 계산). 현재 코드는 `done_for_day`와 `calculated`를 `unknown`으로 분류한다. 그 상태의 주문은 종결로 인정되지 않아 **회차가 열린 채 남는다**(에러가 아니라 보수적 동작이며, 남았을 때는 8절의 수동 종료 도구를 쓴다). 판정 대상은 아니고 정보다.
- `credential_hygiene`: 키·시크릿의 **길이**와 따옴표/공백 포함 여부(값은 없음).
- `manual_action_required`, `cleanup`: 테스트 주문이 남았을 수 있을 때 표시. 반드시 확인(6절).

## 6. 실패했을 때 조치

| 증상 | 조치 |
|---|---|
| 종료 코드 3, "missing environment variable(s)" | 3-1·3-2 수행. `systemd-run`을 `-p EnvironmentFile=`과 함께 썼는지 확인 |
| R1/R2 UNEXPECTED, 401·403 | 키가 paper용인지, 길이가 기대값인지(3-1), 중복 줄이 오래된 값을 덮고 있지 않은지(3-3), 발급 화면에서 키를 재생성했는지 확인 |
| 429·5xx·`transport_error` | 몇 분 뒤 재실행. 반복되면 VM 외부 네트워크/Alpaca 상태 확인 |
| **FAIL이 하나라도 있음** | 그 단계의 `note`와 코드 위치를 대응시켜 `core/paper_execution.py`를 수정하고(`order_by_client_id`의 404 처리, `submit_plan`의 422 분기, `classify_order_state`), `tests/test_paper_execution.py`·`tests/test_champion_order_path.py`의 mock 가정도 실제 응답에 맞게 고친 뒤 다시 검증한다. **FAIL이 해소되기 전까지는 `champion_paper_trade.py --submit`을 쓰지 않는다.** |
| W2b FAIL(중복 주문 생성) 또는 `manual_action_required: true` | Alpaca paper 대시보드 > Orders에서 `client_order_id`가 `qverify-`로 시작하는 주문이 열려 있는지 확인하고 모두 취소한다. 체결된 게 있으면 Positions에서 청산한다. 확인 전에는 다른 주문 작업을 하지 않는다 |
| W1에서 주문이 체결됨 | 도구가 이후 단계를 중단하고 취소를 시도한다. 그래도 paper 포지션이 남았는지 확인 후 정리하고, `--limit-price`를 시장가보다 훨씬 낮게 잡아 재실행 |
| 중간에 프로세스가 죽었음(SSH 끊김 등) | 도구는 `finally`에서 취소를 다시 시도하지만 프로세스가 강제 종료되면 실행되지 않는다. 대시보드에서 `qverify-` 주문을 직접 확인·취소 |
| UNEXPECTED가 재실행해도 반복 | 리포트 JSON의 해당 단계 `observed`(응답 코드/메시지)를 기록해 코드 담당자에게 넘긴다. 값(키)은 리포트에 없다 |

## 7. 실행 후 기록

- 리포트 JSON에는 키 값이 없지만(길이만), 홈 디렉터리 파일이므로 공유 전에 내용을 한 번 훑어본다. `data/`에는 두지 않는다.
- `docs/SESSION_HANDOFF.md`와 `PROGRESS.md`에는 **단계별 PASS/FAIL/UNEXPECTED, 실제 응답 코드(특히 W2의 중복 응답 코드), 실행 일시, 읽기 전용/쓰기 여부**만 적는다. 키·시크릿·계정 ID·이메일은 적지 않는다.
- PASS가 나와도 이 결과는 "paper API 가정 5개 일치"까지다. 배포·운영 검증이 끝났다고 표시하지 않는다.

## 8. 관련 도구: 실행 회차 수동 종료 (`scripts/paper_run_admin.py`)

조회 실패 등으로 회차가 열린 채 남았을 때 쓰는 도구다. 같은 방식으로 실행한다.

```bash
# 회차 목록 (열린 것만: --status open)
sudo -u quant /opt/quant/.venv/bin/python /opt/quant/scripts/paper_run_admin.py list --status open
# 수동 종료: 브로커에서 미종결 주문이 보이면 거부(종료 코드 2). 사유는 필수이며 감사 로그에 남는다
sudo systemd-run --wait --collect --pipe -p User=quant -p WorkingDirectory=/opt/quant -p EnvironmentFile=/opt/quant/.env \
  /opt/quant/.venv/bin/python scripts/paper_run_admin.py close --run-id r00012 --reason "사유"
# 미종결·조회 불가여도 강제로 닫을 때만 --force (감사 로그에 forced로 기록). 강제 종료 뒤 다음 실행은 새 회차·새 주문 ID를 받으므로
# 브로커에 남은 옛 주문과 겹쳐 노출이 두 배가 될 수 있다. 먼저 대시보드에서 옛 주문을 정리한다
```

키가 없는 상태에서는 브로커 조회가 불가능하므로 `--force` 없이는 닫히지 않는다. 감사 로그는 `paper_run_admin.py audit [--run-id r00012]`로 본다.
