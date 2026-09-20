# 다음 감독: Day 4 입력 수령과 실제 PIT 인증

Day 4는 미완료다. 새 자료 없이 Day 3 백테스트, 이전 SEC/MSCI 원천 수집 또는 이번
입력 요청 생성을 반복하지 않는다. `input_request.md`에 조회 키·필드·공식 접근 경로가 있다.

1. 사용자가 알려준 기존 데이터 경로나 새로 추가된 PIT export가 있는지 먼저 확인한다.
2. 새 자료가 있으면 별도 디렉터리에 원문/조회시각/해시를 보존하고 요청 목록과 원천의 전체
   역사적 모집단을 대조한다. 원본 진단 키를 인증된 모집단으로 간주하지 않는다.
3. 구성·섹터·공개 주식수·안정적인 증권 ID/단위·가격/기업행사 증거가 같은 기간에 충족되는지
   검사한다. 현재 섹터나 미래 첫 주식수로 채우지 않는다.
4. 인증된 기간에 대해서만 기존 `../day4/RESUME_NOTE.md`의 S6 상세 사전 판단 절차,
   다음 시가 5/10/25bp 재현, S1 공통 날짜 비교를 진행한다. 모든 조건 충족 전 완료 표식 금지.

이번 요청 패키지 무결성/코드가 의심되거나 수정된 경우에만:

```bash
cd /opt/quant
.venv/bin/python -m pytest -q docs/experiment_validation/day4_input_handoff_20260920/test_handoff.py docs/experiment_validation/day4/test_satellite_audit.py
.venv/bin/python docs/experiment_validation/day4_input_handoff_20260920/verify_handoff.py
```

위 검사는 PIT 데이터나 성과를 생성하지 않는다. `--require-complete`를 붙이면 현재는
종료 코드 2다. 결과/보존 검사는 `validation.json`, 해시는 `result_hashes.json`, 실제 게시
확인은 `publication.json`에 있다. 원문 HTML과 `.before` 백업은 로컬 보존만 한다.
기존 worktree/index/main·미커밋 연구·서비스·브로커 설정을 변경하지 않는다.
