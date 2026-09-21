# 다음 감독: Day 4 실제 PIT 입력 확보 후 재개

2026-09-21 UTC 현재 Day 4는 BLOCKED다. 로컬 3,482개 중 변경 18개는 ETF 가격
캐시이며 새 PIT 입력은 없다. 인증 반기/공통 거래일 0개, 비교 6개 NOT_EVALUABLE.
S6의 실제 다음 시가 재현과 S1 공통 비교가 미완료이므로 Day 5로 넘어가지 않는다.

1. 사용자에게 요청한 PIT export/기존 자료 경로의 새 답변부터 확인한다. 필요한
   자료는 `../day4_input_handoff_20260920/input_request.md`에 정리되어 있다.
   새 증거가 없으면 같은 원천 조사·요청 생성·백테스트를 반복하지 않는다.
2. 입력이 생기면 새 디렉터리에 원문·제공자/URL·조회 UTC·SHA-256을 보존하고,
   선정 모집단 전체의 구성/과거 섹터/공개·유효시각/증권·단위/주식수/가격과
   기업행사를 인증한다. 40개 반기 전체가 새 통과 조건은 아니다.
3. 인증 가능한 기간이 생기면 `../day4/RESUME_NOTE.md`의 남은 세부사항을 성과
   조회 전에 체크포인트→근거 문서→즉시 Telegram 순서로 확정한다. 후보와 게이트는
   유지한다. S6 5/10/25bp 다음 거래일 시가 재현과 S1 동일 날짜·비용·초기자본
   비교를 실제로 완료한 뒤에만 완료 표식을 기록한다.

이번 저장 증거 확인 명령(백테스트 아님):

```bash
cd /opt/quant
python3 - <<'PY'
import hashlib, json
from pathlib import Path
p = Path('docs/experiment_validation/day4_reentry_20260921T0320Z')
for name, expected in json.loads((p / 'result_hashes.json').read_text())['artifacts'].items():
    assert hashlib.sha256((p / name).read_bytes()).hexdigest() == expected, name
print('saved evidence hashes PASS; Day 4 remains BLOCKED')
PY
```

감사 코드 변경이나 무결성 문제가 있을 때만 기존 검사를 다시 실행한다:

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider docs/experiment_validation/day4/test_satellite_audit.py
.venv/bin/python docs/experiment_validation/day4/verify_saved.py --require-complete
# 현재 기대 종료 코드 2: 저장 감사 일치 PASS, Day 4 BLOCKED.
```

이번에는 목록/해시/저장 상태만 검증했다. 기존 15 passed는 이전 테스트 결과이며
실제 S6 통과가 아니다. 게시/알림 확인은 `publication.json`을 참조한다.
기존 worktree/index·미커밋 연구·서비스·인증정보를 보존한다.
