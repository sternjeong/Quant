# 다음 자동 감독: Day 4만 수행

Day 3 검증 통과: `../day3_report.md`, `validation.json`, 두 PROGRESS.md 기록을 확인한다.
게시 완료 여부는 `publication.json`의 원격 확인 SHA로 판단한다. 없으면 아래 게시 마무리를
우선하고 Day 3 백테스트를 반복하지 않는다.

- 고정 후보 6개·기준선·선택 게이트 및 원본 spec/manifest/lock 해시를 유지한다.
- Day 4 목표는 S6 PIT 재현과 S1 공통 날짜 비교, `satellite_audit.md`다.
- 실제 available_at/effective_at, 과거 sector, 동일 단위 발행주식수, 상장폐지 가격을 검증한다.
  로컬 도입 커밋 시각은 과거 공개시각 증거가 아니다. 현재 sector/최초 미래 주식수/미래
  구성종목 fallback으로 결측을 채우지 않는다. 검증 불가능한 구간은 명시한다.
- S1 비교에는 Day 3 저장 일별 원장·주문을 사용한다. 공통 일자 집계의 시작 경계/비용 처리를
  명확히 기록한다. S6 데이터가 있는 기간만 평가하고 후보/게이트를 바꾸지 않는다.
- Day 3 최초 실행은 `run_day3.py`로 끝났으며 재실행 방지 장치가 있다. 데이터 재다운로드 금지.
  해시 변조가 의심될 때만 아래 무결성 검사 또는 저장 원장 검증을 실행한다.

```bash
.venv/bin/python -m pytest -q docs/experiment_validation/test_snapshot.py docs/experiment_validation/day2/test_data_contract.py docs/experiment_validation/day3/test_backtest.py
.venv/bin/python docs/experiment_validation/day3/verify_saved.py
```

게시 마무리가 남아 있다면 `/tmp/quant-day3-baseline-backtest-20260919`의
`research/day3-baseline-backtest-20260919`에서 이번 파일만 commit/push한다.
Day 2 연구 브랜치가 부모이며 dirty main은 보존한다. `result_hashes.json`으로 게시 복사본을
대조하고 `git ls-remote origin refs/heads/research/day3-baseline-backtest-20260919`로 확인한다.
서비스/브로커/인증정보/자동 일일 HTML을 조작하거나 커밋하지 않는다.

사전등록 모호함/명백한 결함의 새로운 판단은 체크포인트→근거 문서→즉시 Telegram 순서다.
`notification_log.json`에 이번 판단 전송 성공을 기록했다. Telegram 환경 값은 출력하지 않는다.
