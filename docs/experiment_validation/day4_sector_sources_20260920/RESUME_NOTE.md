# 다음 감독: Day 4 전체 S&P PIT 자료 확보가 선행 조건

Day 4는 BLOCKED다. Day 5로 넘어가지 않는다. 이 기록은 이전 Day 4 SEC 원천 검토의
후속이며, 기존 `../day4/RESUME_NOTE.md`의 입력 계약/누락표는 계속 유효하다.

이번에 2022년 공동 공지와 2023년 MSCI 미국 기업 변경 목록 62행을 확보했다.
MSCI 적용일(2023-06-01)과 S&P 적용일(2023-03-17 종가 후)은 다르다.
MSCI 기업 목록을 S&P500 전체 분류나 최종 확정 이력으로 바꾸어 사용하지 않는다.
5월 발표 기업 목록을 3월 또는 그 이전으로 소급해 가용 처리하지 않는다.

다음 유효 작업은 **전체 선정 모집단**의 다음 자료를 실제로 확보하는 것이다:

1. S&P500 구성/분류의 최종 과거 이력: security_id, 분류 체계, effective_at, available_at,
   수정 빈티지. 현재 섹터, MSCI 예정 목록, 현재 SIC는 대체 자료가 아니다.
2. 같은 증권의 당시 공시 주식수, 접수/공개시각, 주식 종류와 분할 단위.
   이전 Agilent SEC 70행만으로 전체 pool을 인증하지 않는다.
3. 상장폐지/합병 종목까지 포함하는 조정 기준이 일치한 가격·다음 시가·현금 흐름.

실제 인증된 반기가 생기면 성과를 보기 전에 남은 S6 구현 세부를 기존 고정 명세와
champion_strategy.py에 대조하여 체크포인트/문서/즉시 Telegram 순서로 확정한다.
그다음 S6 5/10/25bp 재현과 S1 공통 일자 비교를 실행한다. 미래 데이터, 동일일 종가 체결,
누락 종목 삭제를 허용하지 않는다. 검증 통과 전 완료 표식 금지.

새 자료가 없으면 이번 공지나 이전 SEC probe/캐시/Day 3 백테스트를 반복하지 않는다.
이미 성공한 추출도 반복할 필요 없다. 원문이 바뀌었는지 의심되거나 코드를 수정했을 때만:

```bash
cd /opt/quant
.venv/bin/python -m pytest -q docs/experiment_validation/day4_sector_sources_20260920/test_sector_sources.py docs/experiment_validation/day4/test_satellite_audit.py
```

저장 원문은 `input_manifest.json`의 로컬 파일과 SHA-256으로 확인한다. 원문 전체는 연구
브랜치에 게시하지 않았으므로 worktree에서 필요한 경우 동일한 해시의 로컬 사본을 사용한다.
외부 자료가 변경되면 과거 receipt/원문을 덮어쓰지 말고 별도 빈티지로 기록한다.
완료 요구 검사에 대한 기존 명령은 `../day4/verify_saved.py --require-complete`이며,
현재 기대값은 종료 코드 2(BLOCKED)다. 새 입력 없이 반복 실행할 필요 없다.

게시 브랜치 `research/day4-sector-sources-20260920`, worktree
`/tmp/quant-day4-sector-sources-20260920`; 실제 원격 SHA는 `publication.json`에서 확인한다.
기존 main/연구 worktree/index와 미커밋 작업은 보존한다.
