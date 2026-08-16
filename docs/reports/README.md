# docs/reports/ — 완성된 HTML 리포트 모음

두 종류가 섞여 있다: (1) `analysis/` 파이프라인 산출물의 **읽기용 사본** — 원본은 각
`analysis/<날짜>_<주제>/` 폴더에 있고 재생성은 그쪽 빌드 스크립트로 해야 한다. (2) claude.ai
Artifact로만 존재하던 리포트/강의노트를 **로컬 저장소에 백업**한 것 — 이쪽은 애초에 이 저장소
안에 원본이 없었으므로 이 사본이 유일한 로컬 사본이다. 각 항목에 어느 쪽인지 표시했다.

## 읽는 순서

번호(No.01~10)가 붙은 것들은 그 순서가 곧 읽는 순서다. 두 트랙이 섞여 있다.

**트랙 A — 개념·아키텍처** (독립적, 순서 안 지켜도 무방)
1. No.01 `study_notes_fin_engineering.html` — 금융공학 개념 25가지, 가장 쉬운 입문
2. No.02 `engine_architecture_notes.html` — No.01의 짝문서, 코드가 실제로 어떻게 동작하는지
3. No.03 `quant_lecture_notes.html` — No.01의 수학적 유도판, 가장 무거움

**트랙 B — 전략 리서치** (반드시 순서대로 — 각 편이 앞 편의 한계를 이어받아 검증한다)
4. No.04 `kostolany_market_report_2026-08-12.html` — 코스톨라니 국면매매 원조 검증, 강세장에서 왜 졌는지 진단
5. No.05 `bull_market_momentum_rotation.html` — No.04의 대안으로 모멘텀 로테이션 제시
6. No.06 `momentum_rotation_multiasset_extension.html` — No.05의 한계(과최적화·거래비용 등) 4개 타개
7. No.07 `momentum_rotation_gfc_validation.html` — No.06 챔피언을 2008년 금융위기로 검증
8. No.08 `momentum_rotation_2022_dotcom_stress.html` — No.07 챔피언을 닷컴버블·2022년 약세장으로 추가 검증
9. No.09 `momentum_rotation_individual_stocks.html` — 섹터 ETF에 개별주를 섞어봤더니 샤프가 급등했지만, 사후편향 의심을 직접 재검증(결론: 아직 미채택)
10. No.10 `momentum_rotation_point_in_time_verdict.html` — No.09의 의심을 point-in-time 시가총액 인프라를 새로 만들어 최종 검증 — 개별주 확장 기각, 챔피언은 No.07/08 유지로 확정

**트랙 C — 개별주 발굴** (독립, 트랙 B와 이어지지 않음 — 하향식 섹터 로테이션이 아니라 상향식 개별종목 발굴)
- `tenbagger_stock_picking_research.html` — PER/PBR/PEG의 자본공학적 유도 + 이 저장소의 기존
  시장국면·섹터강도 엔진 실측 + 개별주 텐베거 발굴 방법론 종합

**참고용** (독립 문서, 번호 없음, 아무 때나) — `market_regime_sector_strength_note.html`

결론만 빠르게 보고 싶으면 No.10부터 거꾸로(개별주 확장이 왜 기각됐는지 + 최종 챔피언 전략 확정),
왜 그 전략이 나왔는지 이해하려면 No.04→10 순서를 권한다. No.09~10은 "개별주로 확장해봤지만 결국
기각한" 갈래고, 챔피언 전략 자체는 No.07/08 기준(11섹터+채권+금+국제주식+원자재) 그대로다. 트랙
C는 트랙 A/B 어느 쪽과도 순서 의존성이 없어 아무 때나 단독으로 읽어도 된다.

## 파일 목록

### [kostolany_market_report_2026-08-12.html](./kostolany_market_report_2026-08-12.html)
*(analysis 사본, No.04)* "코스톨라니 달걀 이론, S&P500 10대 섹터에서 통했는가" — 코스톨라니 달걀
사이클 이론을 S&P500 + 미국 10개 업종 × 5종목 = 51개 자산에 2015-01-01~2026-08-12 기간으로
실제 백테스트해서 검증한 리포트. 08절 "크로스전략 검증"에서 아래 No.05~08 모멘텀 로테이션
후속 시리즈로 연결된다. 원본: `analysis/kostolany_market_report_2026-08-12/final_report.html`
(빌드: 같은 폴더의 `build_report.py`) — 그쪽 폴더에서 후속 실험이 계속 추가되는 중이라 이 사본은
주기적으로 다시 복사해야 최신 상태를 유지한다.

### [bull_market_momentum_rotation.html](./bull_market_momentum_rotation.html)
*(Artifact 백업, No.05)* "강세장엔 평균회귀가 아니라 추세추종" — 위 코스톨라니 리포트(No.04)가
"코스톨라니 국면 매매가 왜 7년 강세장에서 SPY에 졌는지"를 진단한 데 이은 후속 리포트. 딥서치로
찾은 추세추종 + 12개월 듀얼 모멘텀 섹터 로테이션(GICS 11개 섹터, 월 리밸런싱, 상위 3개 동일비중,
후보 부족 시 자동 현금화)을 같은 기간·같은 섹터로 실측 — 누적수익률·MDD·샤프 세 지표 모두
SPY와 코스톨라니 로테이션을 이겼다는 결론과 그 근거(Antonacci 듀얼 모멘텀, 12-1 모멘텀 팩터 등)를
담고 있다.

### [momentum_rotation_multiasset_extension.html](./momentum_rotation_multiasset_extension.html)
*(Artifact 백업, No.06)* "멀티에셋으로 한계를 넘다" — 위 모멘텀 로테이션 리포트(No.05)가 남긴
한계 4가지(과최적화 의심·이진 시장필터·크래시 자체는 못 피함·거래비용 미반영)를 딥서치 근거로
찾은 방법론 3개(변동성 타겟팅, 회전율 버퍼, 채권·금을 더한 멀티에셋 확장)로 직접 테스트한 5라운드
연구 기록. 변동성 타겟팅과 회전율 버퍼는 예상과 반대로 샤프를 오히려 깎아 기각했고, 멀티에셋
확장(11개 섹터+TLT+IEF+GLD)만 채택 — 왕복 0.1% 거래비용 반영 후에도 샤프 1.05(SPY 0.81),
MDD -14.4%(SPY -34.1%)를 달성했고, 순열검정 200회에서 97.5th 백분위(p&asymp;0.025)로 통계적
유의성까지 확인했다.

### [momentum_rotation_gfc_validation.html](./momentum_rotation_gfc_validation.html)
*(Artifact 백업, No.07)* "2008년 금융위기로 검증하다" — No.06 챔피언에 남았던 숙제 3개(이진
시장필터, 좁은 자산군, 같은 강세장 안에서만 쪼갠 하위기간 검증)를 마저 타개. 연속 시장필터는
예상과 반대로 이진보다 나빠 기각, 국제주식(EFA)·하이일드(HYG)·원자재(DBC)를 더한 유니버스 확장은
채택(샤프 1.10, 하위기간 격차 0.07로 지금까지 최고 강건성). 가장 중요한 결과는 섹터 ETF 이력이
안 닿는 2008년까지 SPY+TLT+GLD 3자산으로 데이터를 넓힌 진짜 아웃오브샘플 검증 — 2007-10~2009-06
금융위기 구간에 SPY 매수보유가 -40.4%(MDD -56.5%) 무너질 때 멀티에셋 모멘텀은 +8.4%를 벌었다.

### [momentum_rotation_2022_dotcom_stress.html](./momentum_rotation_2022_dotcom_stress.html)
*(Artifact 백업, No.08)* "채권도 무너진 해, 전략은 어디로 도망갔나" — No.07 챔피언을 위기 사례
2개로 추가 검증. 닷컴버블(2000~2003, TLT 상장 전이라 VUSTX 뮤추얼펀드로 근사)에서는 SPY보다는
나았지만 손실을 피하진 못해(-10.47% vs SPY -36.06%) 2008년만큼 극적이진 않았다는 균형 잡힌
결과. 반면 2022년 약세장(주식·채권 동시 하락으로 전통적 60/40 분산이 깨진 해)에서는 채권(TLT)
자체가 -33.40%로 최악의 자산이었는데도 17자산 챔피언은 원자재(DBC)·에너지(XLE) 로테이션으로
+4.22%를 기록 — "위기엔 무조건 채권"이 아니라 "그 시점 실제로 강한 자산을 따라간다"는 전략의
진짜 강점을 실제 월별 로테이션 기록으로 확인했다. 시그모이드(비선형) 연속 시장필터도 추가
시도했으나 이진 필터(샤프 1.10)를 넘지 못해(최고 1.06) No.07의 이진 필터 선택을 재확인했다.

### [momentum_rotation_individual_stocks.html](./momentum_rotation_individual_stocks.html)
*(Artifact 백업, No.09)* "개별주를 섞었더니 샤프 1.23 — 근데 믿어도 될까" — 사용자가 "반도체주·
통신주 같은 개별 종목도 로테이션 후보에 넣자"고 요청해 섹터 ETF 11개에 개별주 24종목(반도체·
통신·메가캡테크·금융·헬스케어·소비재·에너지·산업재)을 더해 재검증. 샤프가 0.98(섹터ETF만)→1.23
(혼합)으로 급등했지만, 로테이션 기록을 열어보니 전체 픽의 95.3%가 개별주였고 NVDA·AMD·AVGO
3종목이 반복 편중, 하위기간 샤프 격차 0.74(9라운드 통틀어 최악)를 발견 — 손으로 고른 종목
리스트 자체가 "2026년 시점에 이미 AI 랠리 승자였음을 알고 골랐다"는 사후편향 의심이 제기됐다.
`sample_universe(as_of_date=...)`로 편향 없이 재검증했지만 샤프가 오히려 더 높게(1.33~1.39)
나와, "특정 리스트를 잘못 골랐다"보다 더 구조적인 문제(펀더멘털 데이터가 항상 현재 시점 기준이라
과거 시가총액 스냅샷을 못 씀)를 발견 — 이 결론은 아직 채택하지 않고 No.07/08 챔피언(17자산)을
유지하기로 했다.

### [momentum_rotation_point_in_time_verdict.html](./momentum_rotation_point_in_time_verdict.html)
*(Artifact 백업, No.10)* "사후편향을 걷어내니 샤프가 반토막났다" — No.09가 인프라 부재로 완전히
검증 못 하고 남긴 숙제를 풀었다. 사용자가 "시간이 오래 걸려도 되니 진짜 point-in-time 데이터로
검증하라"고 요청 → 신규 core 모듈 `core/point_in_time_market_cap.py`(yfinance
`get_shares_full()` 발행주식수 이력 x 그 시점 종가로 과거 시가총액 근사) 구축. 구현 중 실제
버그도 발견·수정 — 가격은 분할조정된 값인데 발행주식수는 미조정이라 NVDA는 40배 과소평가,
GE는 5배 과대평가되던 문제(pytest 11개로 검증, `sample_universe(use_point_in_time_market_cap=
True)` 옵션 신설). 이 인프라로 2019-08-12 시점 "진짜로 컸던" 종목 30개를 다시 뽑으니(NVDA·AMD·
AVGO는 표본에 아예 없고 MSFT·AAPL·JPM·XOM 같은 평범한 블루칩) 샤프가 1.23~1.39 → **0.68~0.76으로
폭락, 섹터 ETF 전용(0.98)보다도 나쁨** — No.09의 사후편향 의심이 확정됨. 개별주 확장 갈래는
공식 기각, 챔피언 전략은 No.07/08(17자산) 그대로 유지.

### [tenbagger_stock_picking_research.html](./tenbagger_stock_picking_research.html)
*(analysis 사본, 트랙 C, 독립)* "개별주 텐베거 발굴 방법론 — 자본공학적 밸류에이션과 정량 섹터
분석" — 트랙 B(하향식 섹터/시장 로테이션)와 달리 상향식 개별종목 발굴을 다루는 새 트랙. PER은
고든성장모형(배당할인모형)에서, PBR은 잔여이익모형에서 직접 대수적으로 유도해 "몇 배가 정당한가"를
ROE·요구수익률·성장률의 함수로 재구성하고, 그레이엄 기준(P/E&lt;15·P/B&lt;1.5·그레이엄넘버)·린치의
PEG≈1·무형자산이 PBR을 구조적으로 왜곡시킨다는 회계연구(Baruch Lev)까지 종합해 성장률 티어별
적정 PER/PBR/PEG 표로 수렴시킨다. "지금 어느 섹터가 뜨거운가"는 새 방법론을 만들지 않고 이
저장소의 기존 `core.sector_strength`/`core.market_regime`(IBD RS Rating·200일선·골든크로스 등
이미 검증된 프레임워크)을 그대로 호출해 실측한 결과를 싣는다. 린치의 텐베거 정성 기준·오닐의
CANSLIM·학계 품질팩터(QMJ)를 종합해 만든 스크리닝 규칙(핫섹터+시총상한+PEG+성장률+ROE)을
`core.screener.screen()`으로 S&P500에 실제로 실행한 결과도 포함 — 단 S&P500 유니버스
자체가 진짜 소형 텐베거 후보를 구조적으로 배제한다는 한계를 스스로 드러낸 사례(가장 뜨거운
정보기술 섹터에서 시총상한을 통과한 종목이 하나도 없었음)까지 정직하게 기록했다. 원본:
`analysis/2026-08-16_tenbagger_stock_picking/final_report.html`(빌드: 같은 폴더의
`build_report.py`, 데이터 수집: `gather_data.py`).

### [quant_lecture_notes.html](./quant_lecture_notes.html)
*(Artifact 백업, No.03)* "퀀트 강의노트 — 성과지표·사이징·다각화·검증의 수학적 기초" — 스터디
노트(01)가 개념을 요약했다면 이 문서는 핵심 결과를 처음부터 끝까지 수학적으로 **유도**한다.
0부 예비지식(수익률·분산·상관계수) → 1부 성과지표(샤프지수 √252가 어디서 나오는지, CAGR과
변동성 손실의 AM-GM 부등식 증명 등) → 2부 포지션 사이징(켈리 공식을 로그효용 극대화로 직접
미분해 유도) → 3부 다각화(홀리그레일 공식) → 4부 통계적 검증(순열검정·워크포워드) → 5부
비용·시간가치(XIRR) → 6부 신호결합(Z-점수·히스테리시스) 순, 총 16개 장.

### [study_notes_fin_engineering.html](./study_notes_fin_engineering.html)
*(Artifact 백업, No.01)* "스터디 노트 — 금융공학·수학·로직" — 이 Quant 저장소를 만들며 실제로
사용한 금융공학 개념 25가지를 정리한 개념편. 성과지표(샤프·CAGR·MDD·손익비·칼마·낙폭지속기간),
포지션 사이징(고정%·동일가중·켈리·변동성타겟팅), 다각화(홀리그레일 공식·상관관계 붕괴),
백테스트 검증(룩어헤드 편향·대수의 법칙·순열검정·민감도분석·수익분해·워크포워드), 비용과 시간
(거래비용모델·알파감쇠·XIRR), 신호결합(앙상블스코어링·Z점수·히스테리시스·상관관계이력) 6개
섹션. 각 개념이 저장소의 어느 `core/*.py` 함수에 구현돼 있는지까지 연결되어 있다.

### [engine_architecture_notes.html](./engine_architecture_notes.html)
*(Artifact 백업, No.02)* "엔진 아키텍처 노트 — 모듈은 실제로 어떻게 동작하는가" — 위 스터디
노트의 짝문서. "전략 저장 → 백테스트 → 지표 계산 → 검증 → 저장" 파이프라인에서 실제 함수들이
어떤 순서로 데이터를 주고받는지를 6개 모듈(`strategy_engine`, `backtest_engine`,
`position_sizing`, `portfolio`, `market_regime`, 공통 설계 패턴)로 나눠 의사코드와 함께 설명한다.
레지스트리 패턴, 6종 전략 스키마 통일(`evaluate_boolean_signal`), 앙상블 스코어링, 순환참조
회피(지연 import), `compute_*`/`get_*` 계층 분리 등 이 저장소 전반의 설계 원칙이 정리돼 있다.

### [market_regime_sector_strength_note.html](./market_regime_sector_strength_note.html)
*(Artifact 백업)* "시장 국면 판단 + 섹터/테마 강도 지표 — 설계 노트" — [docs/MARKET_REGIME_SECTOR_STRENGTH_SPEC.md](../MARKET_REGIME_SECTOR_STRENGTH_SPEC.md)를
그대로 HTML로 옮긴 것(내용은 동일, 새 리서치 아님). 리서치 근거(200일선/골든·데드크로스/시장폭/
IBD RS Rating/RRG)와 시장 국면 점수 공식(4개 신호 가중합), 섹터/테마 강도 계산식을 마크다운보다
읽기 편한 형태로 보고 싶을 때 이쪽을 보면 된다.

## 여기 없는 문서

- `PROGRESS.md` (저장소 루트) — 시간순 작업 로그, 항상 세션 시작 시 먼저 읽어야 하는 문서라 루트에 유지.
- `README.md` (저장소 루트) — 프로젝트 설치/실행 가이드, GitHub 관례상 루트에 유지.
- `deploy/DEPLOYMENT_ORACLE.md` — Oracle Cloud 배포 가이드. 같은 폴더의 `setup_vm.sh` 등 배포
  스크립트와 상대 경로로 묶여 있어 `deploy/`에 유지.
- `analysis/*/*.html` 원본, `analysis/*/*.md` — 파이프라인이 실제로 읽고 쓰는 산출물 원본. 사본은
  위에 있지만, 재생성이 필요하면 원본 폴더의 빌드 스크립트를 다시 돌려야 한다.
- claude.ai에만 있고 여기 아직 안 옮긴 Artifact 2개("3분커리", "온톨로지 강의노트") — 이 Quant
  저장소와 무관한 주제라 제외했다.
