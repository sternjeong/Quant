# 다음 감독: Day 4 실제 PIT 자료 확보부터

Day 4는 미완료다. 새 자료가 없는 재개에서는 같은 요청 패키지/공식 문서/백테스트를
다시 만들지 않는다. 후보·기준선·게이트는 그대로다.

1. 사용자가 전달한 기존 데이터 경로나 새 PIT export를 확인한다. 이전 검색 시점·범위는
   `local_input_delta.json`, 파일 목록은 `local_scan.csv.gz`에 있다. 이 목록은 데이터
   인증이 아니며 원본 캐시를 실험에 편입하라는 지시도 아니다.
2. 신규 입력이 있으면 별도 디렉터리에 원문·출처·조회 UTC·SHA-256을 보존한다.
   `../day4_input_handoff_20260920/input_request.md`의 전체 모집단/필드 계약과 대조한다.
3. 공개/유효시각, 당시 섹터, 증권 ID/단위, 공시 주식수, 가격/기업행사/상장폐지 입력이
   같은 기간에 인증돼야 한다. 40개 반기 전부를 기다려야 한다는 새 게이트는 없다.
4. 인증된 기간이 생기면 `../day4/RESUME_NOTE.md`대로 남은 세부를 성과 조회 전에
   체크포인트→판단 기록→즉시 Telegram 순서로 확정한다. S6 5/10/25bp 다음 거래일
   시가 재현과 S1 공통 일자 비교 후에만 완료 여부를 판정한다. Day 5는 그 다음이다.

이번 결과의 무결성 검사가 필요한 경우(백테스트 재실행 아님):

```bash
cd /opt/quant
python3 - <<'PY'
import hashlib, json
from pathlib import Path
p = Path('docs/experiment_validation/day4_reentry_20260920T1047Z')
m = json.loads((p / 'result_hashes.json').read_text())
for name, expected in m['artifacts'].items():
    assert hashlib.sha256((p / name).read_bytes()).hexdigest() == expected, name
print('saved evidence hashes PASS; Day 4 remains BLOCKED')
PY
```

이전 감사 코드가 바뀌거나 무결성이 의심될 때만 아래를 실행한다.

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider docs/experiment_validation/day4/test_satellite_audit.py
.venv/bin/python docs/experiment_validation/day4/verify_saved.py --require-complete
# 인증 자료가 없는 현재 상태의 완료 요구 검사는 종료 코드 2(BLOCKED).
```

새 증거 없이는 과거 성공 테스트도 반복할 필요가 없다. 게시 여부는 `publication.json`에
기록한다. 기존 worktree/index·미커밋 연구·서비스는 보존한다.
