# docs/reports/ — 완성된 HTML 리포트 모음

원본이 아니라 **읽기용 사본**이다. 각 리포트는 `analysis/<날짜>_<주제>/` 폴더의 파이프라인 스크립트가
같은 csv/json/pkl 데이터를 가지고 다시 생성하는 산출물이므로, 재생성이 필요하면 원본 폴더에서
빌드 스크립트를 다시 돌려야 한다 (여기 사본을 직접 고치지 않는다).

## 파일 목록

### [kostolany_market_report_2026-08-12.html](./kostolany_market_report_2026-08-12.html)
"코스톨라니 달걀 이론, S&P500 10대 섹터에서 통했는가" — 앙드레 코스톨라니의 달걀 사이클 이론을
S&P500 + 미국 10개 업종(반도체/통신/SW/금융/헬스케어/에너지/임의소비재/필수소비재/산업재/리츠)
× 5종목 = 51개 자산에 2015-01-01~2026-08-12 기간으로 실제 백테스트해서 검증한 리포트. 방법론
(method) → 대상 유니버스(universe) → 헤드라인 결과 → 종목별/섹터별 성과 → 하이퍼파라미터
튜닝 근거 → 포트폴리오 결합 성과 → 대표 사례 → 결과표 → 결론 → 한계(caveats) 순으로 구성된
자기완결형(외부 파일 의존 없음) HTML 문서.

- **원본 생성 파이프라인**: `analysis/kostolany_market_report_2026-08-12/build_report.py`
  (`template.html`의 placeholder를 데이터로 채워 `final_report.html`을 만듦)
- **원본 위치**: `analysis/kostolany_market_report_2026-08-12/final_report.html` (이 폴더의 사본은
  2026-08-13 기준 스냅샷 — 원본 폴더에 스코어링/튜닝 실험이 계속 추가되고 있어 최신 버전은 원본을
  확인할 것. 진행 상황은 같은 폴더의 `RESUME_NOTES.md` 참고)
