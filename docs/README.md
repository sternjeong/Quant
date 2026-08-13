# docs/ — 기획·스펙 문서 색인

이 폴더는 저장소 루트에 흩어져 있던 기획/스펙 마크다운 문서를 모아둔 곳이다. 각 문서가 어떤
내용을 담고 있는지 훑어보고 필요한 문서만 열어보기 위한 색인 역할을 한다.

구현 로그(무엇을 언제 왜 했는지 시간순 기록)는 여기 없고 저장소 루트의 `PROGRESS.md`에 있다.
아래 문서들은 대부분 "설계 논의 과정을 정리한 노트"이며, 각 문서 본문에 `PROGRESS.md`의 해당
날짜 항목을 참고하라는 링크가 달려 있다.

## 파일 목록

### [SPEC.md](./SPEC.md)
프로젝트 전체의 확정 스펙 (v1.0). 개인용 미국 주식 도우미 대시보드의 목적, 기술 스택
(Streamlit + SQLite + yfinance), 그리고 모듈 A~H(백테스팅, Threads 요약, 관심종목 모니터링,
거장 포트폴리오, 퀀트 스크리너, 밸류에이션, 매크로 대시보드, 포트폴리오 관리) 구성을 정의한다.
다른 모든 스펙 문서가 이 문서의 모듈 체계를 전제로 확장된 것이므로 가장 먼저 읽으면 좋다.

### [BOLLINGER_STRATEGIES_SPEC.md](./BOLLINGER_STRATEGIES_SPEC.md)
볼린저 밴드 4대 매매법(스퀴즈/추세추종/추세반전/다이버전스) 구현 설계 노트. 유튜브 대본을
수학적 정의 → 지표 함수 → 조건 평가기 → 구체 전략으로 옮기는 워크플로를 처음 확립한 문서이며,
이후 캔들스틱 스펙이 동일 워크플로를 재사용한다. 진입가 기준 손절(entry-relative stop-loss)을
백테스트 엔진의 일반 기능으로 추가한 결정도 여기서 나왔다. 상태: 구현 완료.

### [CANDLESTICK_PATTERNS_STRATEGY_SPEC.md](./CANDLESTICK_PATTERNS_STRATEGY_SPEC.md)
캔들스틱 패턴(마루보즈/핀바/도지/장악형/인사이드바/관통형/모닝스타·이브닝스타/적삼병·흑삼병/
삼법형) 9개 카테고리를 지표로 구현한 설계 노트. 손절/익절이 원문에 명시된 패턴만 완성된 매매
전략으로 등록한다는 원칙(추측으로 지어내지 않음)을 Bollinger 스펙에서 그대로 이어받았다.
상태: 구현 완료.

### [MARKET_REGIME_SECTOR_STRENGTH_SPEC.md](./MARKET_REGIME_SECTOR_STRENGTH_SPEC.md)
시장 전체가 강세/약세 국면인지, 섹터·테마별 모멘텀이 얼마나 센지를 정량화하는 지표 설계 노트.
`core/market_regime.py`, `core/sector_strength.py`의 근거가 된 업계 표준 방법론 리서치 결과를
포함한다. 매크로 대시보드(모듈 G) 페이지의 새 탭으로 구현됨. 상태: 구현 완료.

### [SECTOR_LEADER_GROWTH_RELATIONSHIP_SPEC.md](./SECTOR_LEADER_GROWTH_RELATIONSHIP_SPEC.md)
섹터별 대표 ETF·대장주·성장주 세 그룹의 가격 흐름 간 정량적 관계(민감도/동조화/상대강도)를
보여주는 독립 페이지 설계 노트. 초대형주가 "성장주" 분류에 섞이는 문제 보정, 기술주 테마 세분화
(방산/냉각/사이버보안/클라우드/로보틱스), 대형주→소형주 레깅 후보 플래그 등 같은 날 후속 확장
요청까지 반영되어 있다. 상태: 구현 완료.

### [STRATEGY_BATCH_GENERATION_SPEC.md](./STRATEGY_BATCH_GENERATION_SPEC.md)
유튜브 스크립트 여러 개를 한 번에 입력하면 각각을 분석해 튜닝 대상이 될 백본 전략을 대량
생성하는 모듈의 설계 노트. 기존 `core/nl_strategy.py::interpret_strategy_text`를 그대로
재사용하는 부분과 신규로 필요한 부분을 구분해 정리했다. 가장 짧은 문서(60줄).

### [STRATEGY_TUNING_ENGINE_SPEC.md](./STRATEGY_TUNING_ENGINE_SPEC.md)
가장 크고 계속 갱신되는 문서(770줄+, 16개 절). 다종목(S&P500 ~100개) 미세튜닝 엔진의 전체
설계사(design history)다. 종목 스타일 분류, 워크포워드 검증, 국면별(약세장/강세장) 분리
트레이닝, 종목 자체 추세(상승/하락/횡보) 기준 데이터셋 분리, 스윙 트레이딩 보유기간 상한,
야간 CI 배치 안정성 수정 등 튜닝 엔진이 발전해 온 모든 결정과 그 이유가 절 번호순으로 쌓여있다.
튜닝 엔진 코드(`core/strategy_tuning.py`)를 건드리기 전에는 반드시 참고. 장기적으로 계속
갱신되는 "살아있는" 문서이므로 최신 절(가장 큰 번호)이 현재 동작을 반영한다.

## [reports/](./reports/) — 완성된 HTML 리포트 사본

`analysis/` 아래 각 분석 파이프라인이 만들어내는 최종 HTML 리포트를 읽기 편하게 한곳에 모아둔
사본 폴더. 원본(빌드 스크립트가 실제로 참조/재생성하는 파일)은 각 `analysis/<날짜>_<주제>/`
폴더에 그대로 있고, 여기 있는 건 훑어보기용 스냅샷이다. 목록/설명은 [reports/README.md](./reports/README.md) 참고.

## 여기 없는 문서

- `PROGRESS.md` (저장소 루트) — 시간순 작업 로그, 항상 세션 시작 시 먼저 읽어야 하는 문서라 루트에 유지.
- `README.md` (저장소 루트) — 프로젝트 설치/실행 가이드, GitHub 관례상 루트에 유지.
- `deploy/DEPLOYMENT_ORACLE.md` — Oracle Cloud 배포 가이드. 같은 폴더의 `setup_vm.sh` 등 배포
  스크립트와 상대 경로로 묶여 있어 `deploy/`에 유지.
- `analysis/*/*.html` 원본, `analysis/*/*.md` — 파이프라인이 실제로 읽고 쓰는 산출물 원본. 사본은
  위 `reports/`에 있지만, 재생성이 필요하면 원본 폴더의 빌드 스크립트를 다시 돌려야 한다.
