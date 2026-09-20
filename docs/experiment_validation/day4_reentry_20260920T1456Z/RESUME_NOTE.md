# 다음 자동 감독: Day 4 실제 PIT 입력 확보

Day 4는 미완료다. 2026-09-20 14:56 UTC 재개에서는 새 파일이 없고 가격 캐시 20개의
메타데이터 차이만 발견됐다. 인증 반기/공통 거래일은 0개다. 이번 무결성 PASS를
실제 S6 재현 통과로 취급하거나 Day 5로 넘어가지 않는다.

1. 새 PIT export 또는 사용자가 전달한 기존 자료 경로가 있는지 먼저 확인한다.
   마지막 검색 범위·시각은 `local_input_delta.json`, 비교 목록은 `local_scan.csv.gz`다.
   같은 공급자 소개/SEC 단일 회사/GICS 공지 수집이나 요청 패키지를 반복하지 않는다.
2. 자료를 받으면 원문·제공자/URL·조회 UTC·SHA-256을 새 디렉터리에 보존하고
   `../day4_input_handoff_20260920/input_request.md`의 입력 계약과 대조한다.
   전체 선정 모집단의 구성·과거 섹터·공개/유효시각·증권/단위·주식수와 가격/기업행사가
   같은 기간에 인증돼야 한다. 40개 반기 전부를 기다려야 한다는 새 게이트는 없다.
3. 실제 평가 가능한 기간이 생기면 `../day4/RESUME_NOTE.md`의 남은 세부사항을
   성과 조회 전에 체크포인트→판단 문서→즉시 Telegram 순서로 확정한다.
   S6 5/10/25bp 다음 거래일 시가 재현과 S1 동일 날짜·비용·초기자본 비교를 수행한다.
   실제 PIT·누수/체결·공통 비교 통과 뒤에만 완료 표식을 기록한다.

이번 저장 결과의 무결성이 의심될 때 확인하는 명령(백테스트 재실행 아님):

```bash
cd /opt/quant
python3 - <<'PY'
import hashlib, json
from pathlib import Path
p = Path('docs/experiment_validation/day4_reentry_20260920T1456Z')
m = json.loads((p / 'result_hashes.json').read_text())
for name, expected in m['artifacts'].items():
    assert hashlib.sha256((p / name).read_bytes()).hexdigest() == expected, name
print('saved evidence hashes PASS; Day 4 remains BLOCKED')
PY
```

감사 코드가 바뀌거나 데이터 무결성 문제가 있을 때만 기존 검사를 다시 실행한다:

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider docs/experiment_validation/day4/test_satellite_audit.py
.venv/bin/python docs/experiment_validation/day4/verify_saved.py --require-complete
# 현재 인증 자료가 없는 상태: 완료 요구 종료 코드 2(BLOCKED).
```

직전 15 passed는 이전 테스트 결과로 보존했다. 새 입력/코드 변경 없이 성공 테스트나
결정론적 백테스트를 반복할 필요가 없다. 원격 게시/알림 확인은 `publication.json`을 본다.
기존 worktree/index·미커밋 연구·서비스·인증정보는 보존한다.
