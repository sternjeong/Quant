# 다음 자동 감독: Day 4 재개, 아직 미완료

2026-09-19 감사는 BLOCKED다. `../satellite_audit.md`, `audit_results.json`, `validation.json`을 읽는다.
테스트 78개 및 독립 파일 대조 PASS는 코드/감사 일치 검사다. 실제 PIT 재현과 공통 성과 비교는
아직 수행할 수 없으므로 Day 4 완료 표식을 쓰거나 Day 5로 넘어가지 않는다.

## 먼저 확보할 증거

`rebalance_coverage.csv`/`member_coverage.csv.gz`가 반기별 원본 종목·누락 날짜를 제공한다.
성과를 보지 않고 사전 계약과 기존 구현에 따라 아래 자료를 인증한다.

1. 구성종목: 안정적인 security_id, effective_at, available_at, 출처와 수정 빈티지.
   공개시각이 신호 종가 이하여야 하며 원본 ticker 접미사를 무조건 제거하지 않는다.
2. 같은 식별자의 과거 섹터: effective_at/available_at 및 과거 분류 출처.
   현재 Wikipedia 섹터를 과거에 붙이거나 미상 섹터를 임의 한 그룹으로 모으지 않는다.
3. 발행주식수: 실제 공시/접수시각, 단위, 증권 종류, split-adjustment 기준.
   관측일만으로 가용성을 주장하지 않고, 미래 첫 행으로 fallback하지 않는다.
4. 가격·기업행사: 선정 모집단의 순위 입력과 보유 종목의 신호/다음 시가/종가, 상장폐지·합병
   현금 흐름 및 조회시각/해시. 누락 종목을 삭제하거나 가격을 무한 전방채움하지 않는다.

현재 40개 반기/20,156개 종목·날짜 조합 모두 인증 불가다. 이 결론은 외부에 데이터가 존재하지
않는다는 뜻은 아니다. 기존 `local_source_search.json`과 `input_manifest.json`을 먼저 보고,
새로운 검증 가능 자료를 얻었을 때만 별도 manifest/출처로 추가한다. 원본 spec/manifest/lock,
Day 1~3 및 이번 진단 입력을 덮어쓰지 않는다. 유료 구독/인증 변경은 이번 작업에 포함하지 않는다.

## 입력이 확보된 다음

- 체크포인트 → 사전 해석 문서 → 즉시 Telegram 순서를 따른다. 후보·기준선·게이트는 변경 금지.
- 반기 첫 거래일 시가의 pool/rank에는 전 거래일 종가까지 알려진 값만 쓴다. 기존 선택 함수가
  체결일을 시총 조회일로 넘기는 경로를 그대로 호출하지 않는다(`legacy_probes.json`).
- S6의 미명시 상세 숫자는 기존 frozen source/등록 근거를 대조하고 성과를 보기 전에 확정한다.
  이번 감사는 legacy 숫자를 새 사전등록 명세로 승격하지 않았다.
- S1 코어는 Day 3 원장/신호와 규칙을 재사용하고 동일한 5/10/25bp 다음 시가 회계를 적용한다.
- S6은 인증된 입력 기간만 실행한다. S1과 공통 날짜의 경계·초기비용·슬리브 재조정 규약을
  먼저 기록하고 비교한다. 공통 날짜 0개이면 0%나 현금 대체 성과를 만들지 않는다.
- 실제 재현/누수 없음/공통 비교를 모두 충족했을 때만 완료 표식을 추가한다.

## 현재 산출물 확인 명령

```bash
cd /opt/quant
.venv/bin/python docs/experiment_validation/day4/verify_saved.py --require-complete
# 현재 기대 종료 코드 2: 파일 감사 PASS, Day 4 BLOCKED
.venv/bin/python -m pytest -q docs/experiment_validation/test_snapshot.py docs/experiment_validation/day2/test_data_contract.py docs/experiment_validation/day3/test_backtest.py docs/experiment_validation/day4/test_satellite_audit.py
```

이미 성공한 결정론적 Day 3 백테스트와 `day4/capture_inputs.py`를 반복 실행하지 않는다.
무결성 문제가 의심될 때만 위 검사로 대조한다. `capture_inputs.py`는 기존 입력 manifest가 있으면
덮어쓰기를 거절한다. 원래 캐시의 조회시각 미상을 사후 캡처시각으로 채우지 않는다.

## 게시 상태

Day 4 브랜치: `research/day4-satellite-audit-20260919`.
worktree: `/tmp/quant-day4-satellite-audit-20260919`.
게시 성공 여부는 `publication.json`의 원격 SHA 대조로 확인한다. 없으면 같은 브랜치의
commit/push 마무리가 남아 있다. 자동 생성 일일 HTML/.env/서비스 상태를 커밋하지 않는다.

기존 Day 3 worktree/index는 별도로 남아 있고 건드리지 않았다. Day 4 브랜치에는 미게시된
Day 3 증거를 의존 파일로 복사했다. 게시 기록이 없는 Day 3 브랜치를 게시 성공으로 간주하지 않는다.
dirty main/기존 미커밋 연구 및 서비스는 보존한다.
