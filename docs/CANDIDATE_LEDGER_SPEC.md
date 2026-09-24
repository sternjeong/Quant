# 후보 shadow 원장 설계 (RES-01)

상태: **구현(단위 테스트 수준)**. 관측 전용 인프라이며 주문에 영향이 없다. 기존 전략·주문 경로·스케줄러에 **연결돼 있지 않다**(연결은 다음 단계). 이 문서의 어떤 수치도 성과·승률 개선을 주장하지 않는다.
연구 배경과 검증·거절 계약은 [정보 수집·판단 엔진 연구](./INFORMATION_DECISION_ENGINE_RESEARCH.md)의 RES-01, 공통 시간 계약, 최소 데이터 계약, 검증과 거절 계약을 따른다.

## 무엇을 하는가

전략이 만든 **전체 후보 집합**을 동결하고, 채택(selected)·보류(held)·거절(rejected)·데이터 결측(missing_data) 후보를 **같은 진입·청산·비용 계약**으로 끝까지 추적한다. 그래서 "채택이 보류/거절보다 비용 후 기대값을 실제로 높였는가"를 사후에 (선택편향 없이) 물을 수 있다. 원전략의 판단·점수·주문안을 그대로 기록만 하며 바꾸지 않는다.

## 사전 고정 계약

코드 상수가 곧 사전 등록이다(`core/candidate_ledger.py`). 결과를 본 뒤 바꾸면 탐색 결과로만 취급한다.

| 항목 | 고정값 | 근거·주의 |
|---|---|---|
| 진입 | decision_cutoff 이후 첫 미국 정규장 세션의 **시가** | `core/trade_ledger.py`의 "t 종가 이후 신호 → t+1 시가 체결"을 시각으로 일반화. 날짜만 준 cutoff는 그 날 미 동부 23:59:59(장 마감 후)로 본다. 시각이 있으면 개장(09:30 미 동부, DST 반영) 이전은 당일 시가, 이후(정각 포함)는 다음 세션 시가 |
| 청산 | 진입 세션 + horizon 거래일 뒤 세션의 **시가** | 종가/시가를 섞지 않고 trade_ledger의 체결 관례와 통일. 거래일력은 SPY 세션 |
| 주 horizon | `PRIMARY_HORIZON_DAYS = 20` 거래일 1개 | 판정은 이 horizon에서만 가능 |
| 진단 horizon | 5, 60 거래일 | `role='diagnostic'`, 다중검정 대상. 저장·표시만 하고 판정 불가 |
| 비용 | 편도 5/10/25bp 모두 저장(`COST_SCENARIOS_BPS`), 주 검정 `PRIMARY_COST_SCENARIO='10bp'` | 수수료/슬리피지 배분은 가정값이며 특정 증권사 요율이 아님. 왕복 순수익은 trade_ledger의 전량 매수·전량 매도와 동일(테스트에서 독립 구현과 대조) |
| 주 검정 대상 | `PRIMARY_TARGET='net_excess_spy'` = 비용 후 수익 − 같은 진입/청산 시가 기준 SPY 수익 | `P(비용 후 벤치마크 초과수익 > 0)` 계열을 사전 선택. 승률만 보지 않는다 |
| 섹터 잔차 | 비용 후 수익 − 섹터 ETF 수익(β=1 단순 차감) | 회귀 잔차가 아니며 진단용. 섹터 ETF가 없으면 NULL |
| 가격 기준 | 캐시된 원시 Open(`auto_adjust=False`) | 분할은 캐시에 반영, 배당은 미반영. Adj Close 비율 조정은 캐시가 증분 병합돼 조정 기준일이 행마다 다를 수 있어 쓰지 않음 |

## 시간 계약과 PIT 인증

`source_publication → system_first_seen → extraction_completed → decision_cutoff → next_executable_fill`을 후보 판단마다 따로 저장한다(모두 naive UTC).

- 없는 필드는 **NULL**이며 지어내지 않는다. 5개가 모두 있고 순서가 맞을 때만 `pit_certified=True`. 누락·순서 위반 사유는 `pit_note`에 남긴다.
- `next_executable_fill`은 결과 추적이 진입 세션을 확정할 때 그 세션 개장 시각으로 채우고 PIT 여부를 다시 계산한다.
- 어댑터는 시간 계약을 지어내지 않는다. 호출부가 실제 기록한 값을 `time_contract`로 넘겨야 한다. 넘기지 않으면 모든 후보가 PIT 미인증이며, 이 경우 판정은 항상 '미입증'이다.
- `stock_discovery`의 `meta.pit_verified=False`(현재 재무·가격 스냅샷)는 집합 meta에 보존된다.

## 테이블 (`core/models.py`, `create_all`로 생성 — 기존 테이블·행에 영향 없음)

- `candidate_batches`: 동결된 후보 집합 1건. `candidate_set_id`(정렬된 티커 집합 + 전략 버전 + 출처 + 정규화된 결정 시각의 해시, unique), `decisions_fingerprint`(같은 집합을 다른 판단으로 다시 기록하려는 충돌 감지).
- `candidate_decisions`: 후보 판단 1건. ticker, strategy_version, decision, decision_reason, rank, scores(JSON), order_proposal(JSON), 시간 계약 5개, pit_certified, pit_note, 정보 원문 참조(url/doc_id/content_hash/revision), event_id, info_cost(JSON). `(candidate_set_id, ticker)` unique.
- `candidate_outcomes`: 결정 × horizon 결과. status(pending/final/missing), status_reason, 진입·청산 날짜와 시가, gross_return, net_return_5bp/10bp/25bp, benchmark_return, sector_etf_return, price_basis, exit_rule, detail(JSON). `(decision_id, horizon_days)` unique.

`core/db.py`는 수정하지 않았다. 새 테이블은 `create_all`이 만들며, 기존 컬럼 추가용 `_add_missing_columns` 대상이 아니다(실제 `data/quant.db` 사본에 `init_db()`를 실행해 기존 21개 테이블의 행 수가 변하지 않음을 확인).

## 결과 추적 `update_forward_outcomes(as_of)`

- 종결되지 않은(행이 없거나 pending인) (후보, horizon)만 계산한다. `final`/`missing`은 종결 상태라 재계산하지 않고, pending 행은 같은 행을 갱신한다 → **멱등**(재실행해도 중복 행 없음).
- as_of 이후의 봉은 절대 쓰지 않는다. 청산 세션이 아직 없으면 pending(`horizon_not_reached`).
- 가격은 `price_provider(ticker, start, end)`로 받는다. 기본은 `core.market_data.get_price_history`의 캐시 정책(명시적 end를 주므로 캐시가 덮는 범위는 네트워크 없음). 테스트·오프라인 검증은 공급자를 주입한다. 공급자 예외는 그 티커를 pending(`provider_error: ...`)으로 남기고 나머지는 계속한다.
- **결측은 조용히 0으로 처리하지 않는다.** 수익 컬럼은 NULL이고 사유가 남는다: `decision_cutoff_missing`, `no_price_data`, `not_listed_at_entry`, `no_entry_bar`, `no_exit_bar`, `data_ended_before_entry/exit`(상장폐지·거래정지 의심), `invalid_entry_open/exit_open`. 티커 데이터가 벤치마크보다 5세션(`MISSING_GRACE_SESSIONS`) 넘게 뒤처질 때만 결측으로 확정하고 그 전에는 pending(`ticker_data_lagging`, `price_data_unavailable`)이다.
- 벤치마크(SPY) 가격이 없으면 거래일력을 만들 수 없어 전부 pending(`benchmark_unavailable`).

## 지표와 판정 (`evaluate_selection`, `build_ledger_report`)

- 그룹별: n, 비용 후 기대값(평균), 승률(값>0), 분위수(5/25/50/75/95%), 최대 손실(최솟값), 손익비(이익합/손실합).
- 선택률(coverage) = 채택 / (채택+보류+거절, 결과 있는 후보). 결측 판정 후보는 비교 풀에서 분리해 별도 요약.
- 놓친 기회 비용 = 보류·거절 후보의 평균 초과수익(양수면 채택하지 않아 놓친 기회).
- **동일 선택률 무작위 보류 기준선**: 각 후보 집합에서 채택 수와 같은 수를 무작위로 채택했을 때의 기대값·승률·손익비(해석적 기대값), 시드 고정 몬테카를로 분포(진단용).
- **신뢰구간**: 채택 − 무작위 기준선 증분의 종목 × 날짜 블록 pigeonhole 부트스트랩(종목 군집과 `ceil(horizon×7/5)`일 날짜 블록을 각각 복원추출, 시드 고정, 95% 백분위). 겹치는 label 기간은 블록 길이로 완화할 뿐 purge/embargo와 열어보지 않는 최종 기간을 대체하지 않는다.
- **판정 규칙을 코드로 강제**(`decide_verdict`): 신뢰구간이 0을 포함하면 `미입증`. 다음 중 하나라도 있으면 신뢰구간과 무관하게 `미입증`이다 — 진단 horizon, 주 대상·주 비용 시나리오가 아님, 채택 결과 없음, 표본 부족(채택 <30, 종목 군집 <20, 날짜 블록 <6), 신뢰구간 계산 불가, PIT 미인증 행 존재, 결과 결측률 >10%. 모두 통과하고 0을 배제하면 `양성_검토대상` 또는 `기각_검토대상`이며, 기각 검토는 더 큰 표본(채택 ≥100, 날짜 블록 ≥12)을 추가로 요구한다. 이 결과는 사람이 검토할 후보이며 자동 채택/폐기가 아니다(`auto_decision=False`). 게이트 수치는 제안값이며 실제 검정력 분석으로 대체해야 한다.
- **경고**: 승률이 무작위 기준선보다 높은데 선택률<1이고 기대값·손익비 개선이 신뢰구간으로 입증되지 않으면 `win_rate_selectivity`(승률만 올라 선택률로 설명될 수 있음). 그 밖에 결측률 과다, PIT 미인증, 보류·거절이 채택보다 높은 평균.

## 어댑터 (순수 함수, 기존 모듈 미수정)

- `stock_discovery_to_candidate_set(df, ...)`: `discover_candidates` 결과. composite_score 순위, `selected_n`/`min_composite_score`로 채택 결정, 미채택 중 결측(data_errors·결측 팩터 수 ≥ `max_missing_factors`)은 missing_data, 점수 미달은 rejected, 나머지 held. 원전략이 채택한 행은 결측이 있어도 selected이고 사실은 점수 JSON에 남는다. 결과 DataFrame은 보통 top_n으로 잘려 있으므로 전체 후보를 기록하려면 호출부가 더 큰 top_n으로 실행해야 한다.
- `sector_leaders_to_candidate_set(result, pool=...)`: 대장주·성장주는 selected. 결과에 미채택 후보가 없으므로 호출부가 `pool`을 넘겨야 held/missing_data가 기록된다(없으면 `meta.pool_recorded=False`).
- `champion_satellite_to_candidate_set(result, ...)`: 라이브 스캔 결과(돌파 후보 DataFrame 포함), `compute_satellite_recommendation_point_in_time` 결과(채택만, `new_orders_allowed=False`면 held), `_pick_satellite_at_date` 원형을 받는다. 스캔에서 걸러진 종목은 호출부가 `missing_tickers`/`rejected_tickers`로 넘긴 것만 기록한다.

## CLI

`python scripts/candidate_ledger_update.py [--as-of YYYY-MM-DD] [--strategy-version V] [--horizons 5,20,60] [--no-report] [--json]` — 결과 갱신 후 요약(주 horizon + 진단 horizon)을 출력한다. **스케줄러에 등록하지 않았다.**

## 확인하지 못한 것 · 한계

- 실제 후보 집합을 기록하는 호출부가 없어 실운영 데이터가 0건이다. 실제 캐시 가격으로 진입·청산 날짜와 총수익이 수기 계산과 일치함은 확인했지만(임시 DB, 네트워크 없음), 기록된 후보의 성과는 아직 없다.
- 상장폐지 종목의 청산 가치(폐지 수익률)를 알 수 없어 결측으로만 남긴다. 결측이 성과와 상관되면 결과가 왜곡되므로 결측률 게이트가 있으나 편향 보정은 없다.
- 배당·기업행동 미반영, 시가 체결 가정(호가 스프레드·시장충격은 비용 시나리오에 뭉뚱그림), 거래일력은 SPY 기준(SPY 결측일과 종목 거래일이 다를 수 있음).
- 캐시 정책상 `end`가 저장 범위를 넘으면 기존 `market_data`가 네트워크를 호출한다. 기본 공급자의 빈 결과는 일시 장애와 상장폐지를 구분하지 못하며, 5세션 유예로만 완화한다.
- 부트스트랩은 pigeonhole 근사이며 겹치는 label 구간의 purge/embargo, 다중 전략 동시 검정 보정은 미구현이다. 종목당 결과가 여러 horizon·여러 후보 집합에 중복되는 상관은 종목 군집으로만 반영한다.
- 정보 원문 참조·동일 사건 ID·정보 비용 필드는 저장만 하며 중복 제거·비용 집계 로직은 RES-02 범위로 남겼다.
- paper API·VM·배포·화면은 다루지 않았다.

## 다음 연결 지점 (제안, 미구현)

1. `discover_candidates`/`compute_leader_and_growth`/`compute_satellite_recommendation(_point_in_time)` 호출 직후 어댑터 → `record_candidate_set`을 부르는 관측 훅(주문 경로와 분리, 실패해도 본 흐름을 막지 않도록 try/except). 결정 시각과 실제 수신·추출 시각을 호출부에서 기록해 `time_contract`로 넘긴다.
2. `scripts/candidate_ledger_update.py`를 스케줄러(장 마감 후 일 1회)에 등록하는 결정.
3. 요약 리포트를 화면에 노출할지 여부와 표본이 쌓인 뒤 검정력 분석으로 게이트 수치 교체.
