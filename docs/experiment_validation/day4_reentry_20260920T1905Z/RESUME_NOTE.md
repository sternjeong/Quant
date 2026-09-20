# 다음 감독: Day 4 실제 PIT 입력 인증부터

Day 4는 미완료다. 2026-09-20 19:05 UTC의 새 데이터 파일 12개는 별도 연구 결과이며,
변경된 현재 구성종목/가격 캐시도 과거 모집단·공개시각·섹터 인증의 누락을 해결하지 못했다.
인증 반기/공통 거래일은 0개, S1/S6 비교 6개는 NOT_EVALUABLE이다. Day 5로 넘어가지 않는다.

1. 신규 PIT export 또는 전달받은 기존 자료 경로를 확인한다. 마지막 목록은
   `local_scan.csv.gz`, 범위·시각은 `local_input_delta.json`이다. 현재 구성종목과
   다른 연구의 수익률·통계 결과를 인증 입력으로 대신하지 않는다.
2. 원문·제공자/URL·조회 UTC·SHA-256을 새 디렉터리에 보존하고
   `../day4_input_handoff_20260920/input_request.md`와 대조한다. 선정 모집단 전체의
   구성·과거 섹터·공개/유효시각·증권/단위·주식수·가격/기업행사를 함께 인증한다.
   40개 반기를 전부 인증해야 한다는 새 게이트는 없으며 실제 가용 기간만 평가한다.
3. 평가 가능한 기간이 생기면 `../day4/RESUME_NOTE.md`의 남은 세부사항을 성과 조회 전에
   체크포인트→판단 문서→즉시 Telegram 순서로 확정한다. S6 5/10/25bp 다음 거래일
   시가 재현, S1 동일 날짜·비용·초기자본 비교를 수행하고 모두 통과할 때만 완료 표식을 쓴다.

이번 증거 파일의 무결성 확인(백테스트 재실행 아님):

```bash
cd /opt/quant
python3 - <<'PY'
import hashlib, json
from pathlib import Path
p = Path('docs/experiment_validation/day4_reentry_20260920T1905Z')
m = json.loads((p / 'result_hashes.json').read_text())
for name, expected in m['artifacts'].items():
    assert hashlib.sha256((p / name).read_bytes()).hexdigest() == expected, name
print('saved evidence hashes PASS; Day 4 remains BLOCKED')
PY
```

감사 코드 변경이나 데이터 무결성 문제가 있을 때만 기존 검사를 재실행한다:

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider docs/experiment_validation/day4/test_satellite_audit.py
.venv/bin/python docs/experiment_validation/day4/verify_saved.py --require-complete
# 현재 인증 자료 없음: 완료 요구 종료 코드 2(BLOCKED).
```

이번에는 새 목록/스키마/해시/저장 상태를 검증했다. 이전 15 passed는 이전 결과이고
실제 S6 실행 인증은 아니다. 새 증거가 없으면 동일 백테스트·원천 조사·요청 생성을
반복하지 않는다. 게시/알림 확인은 `publication.json`. 기존 worktree/index·미커밋 연구·
서비스·인증정보는 보존한다.
