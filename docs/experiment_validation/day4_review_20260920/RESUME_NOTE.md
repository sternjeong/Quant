# 다음 자동 감독: Day 4 입력 확보부터 재개

2026-09-20 UTC. Day 4는 BLOCKED다. Day 5로 이동하지 않는다.
`review.md`, `validation.json`, `sec_history_diagnostics.json`을 먼저 읽는다.
기존 전체 누락표와 계약은 `../day4/RESUME_NOTE.md` 및 `../day4/member_coverage.csv.gz`다.

이번에 새 SEC 원문 3개를 확보했고 A(Agilent)의 주식수 70행을 공시 accession과 연결했다.
CIK 표현이 정수와 문자열로 달라 생긴 진단 수집 오류는 수정했다. 최초 실패 receipt도 보존했다.
원문이 이미 있으므로 SEC probe를 재실행하거나 주식수/가격 캐시 전체를 다시 받지 않는다.

다음 유효 작업은 선정 모집단 전체의 **과거 구성종목·섹터·증권 식별자·공개시각**을 검증할 수
있는 새 원천을 확보하는 것이다. SEC 자료를 확대할 경우 각 accession의 원 공시와 수정 공시,
수량 단위·분할·주식 종류 및 당시 가용시각을 인증해야 한다. 현재 SIC는 과거 GICS가 아니다.
상장폐지 종목을 포함한 신호/시가/평가가격과 기업행사 현금 경로도 필요하다.
한 회사의 성공, 웹 문서, 날짜만 있는 캐시를 전체 S6 입력 인증으로 취급하지 않는다.

새 입력으로 인증된 반기가 생긴 뒤에만, 기존 고정 명세와 다음 시가 엔진을 이용해
S6 5/10/25bp 재현 및 같은 날짜의 S1 비교를 수행한다. 새 해석/버그 판단은 사용자 지시의
체크포인트 → 문서 → 즉시 Telegram 순서를 지킨다. 결과로 규칙을 선택하지 않는다.
새 자료가 없으면 같은 검증을 반복하지 말고 입력 확보가 막힌 상태임을 보고한다.

저장 증거가 바뀌었거나 코드 수정 후 확인이 필요한 경우에만:

```bash
cd /opt/quant
python3 docs/experiment_validation/day4_review_20260920/inspect_sec_evidence.py
.venv/bin/python -m pytest -q docs/experiment_validation/day4_review_20260920/test_sec_probe.py docs/experiment_validation/day4/test_satellite_audit.py
.venv/bin/python docs/experiment_validation/day4/verify_saved.py --require-complete
# 마지막 명령 기대값: 파일 감사 PASS, 종료 코드 2, Day 4 BLOCKED
```

새 연구 브랜치 `research/day4-source-review-20260920`, worktree
`/tmp/quant-day4-source-review-20260920`; 게시 SHA는 `publication.json`에서 확인한다.
기존 main과 Day 1~4 worktree/index 및 원본 산출물은 보존한다.
