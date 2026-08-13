# 볼린저 밴드 4대 매매법 구현 스펙 (논의 노트)

> **상태: 구현 완료 (2026-07-15).** 사용자가 유튜브 "볼린저 밴드 최고의 매매전략 4가지"(스퀴즈/
> 추세추종/추세반전/다이버전스) 대본을 제공하며 전부 구현 요청. 확정 스펙은 `SPEC.md`(모듈 A "볼린저
> 밴드 응용 전략 4종" 항목), 구현/검증 상세 로그는 `PROGRESS.md`(2026-07-15 항목) 참고. 이 문서는
> 설계 논의 과정의 기록으로 남긴다.

## 1. 요청 요약

4개 전략 전부 구현. 대화로 확정된 두 가지 결정:
1. **전부 구현** (스퀴즈, 추세추종, 추세반전, 다이버전스) — 순서는 난이도 순(아래 §4).
2. **진입가 기준 손절(entry-relative stop-loss)을 이번에 엔진에 일반 기능으로 추가.** 4개 전략
   전부 "진입 시점 가격 대비" 손절선을 정의하는데, 지금 백테스트 엔진은 완전 무상태(그날의 지표값만
   보고 매일 True/False 판정)라 이 개념 자체가 없음 — 이번 참에 일반 메커니즘으로 구축.

## 2. 기존 엔진 재사용/제약 확인

| 항목 | 확인 결과 |
|---|---|
| 진입/청산 조건이 다른 전략 표현 | `entry_stages`/`exit_stages`(staged 스키마, `simulate_staged_positions`)로 이미 가능 — 4개 전략 모두 진입≠청산 조건이라 **staged 스키마를 1단계짜리(weight=1.0)로 사용**하면 됨. 새 top-level 스키마 불필요. |
| 매도(공매도) 포지션 | 엔진 전체가 롱온리(비중 0~1, 음수 없음 — `compute_equity_curve`/`simulate_staged_positions` 확인). 영상의 "매도 진입"(숏)은 이번 스코프에서 제외 — 매수(롱) 방향만 구현. 숏 지원은 훨씬 큰 별도 작업(청산 손익 계산식 자체가 다름). |
| 진입가 기준 손절 | 없음(grep으로 확인 — `entry_price`/`stop_loss` 개념이 `core/backtest_engine.py`/`strategy_engine.py` 어디에도 없음). 아래 §3.4에서 신규 설계. |
| 볼린저 중심선(mid) 조건 | `_eval_bollinger`는 지금 upper/lower만 지원, mid 없음 — 추가 필요(추세추종 제외 나머지 3개 전략의 익절 조건이 전부 중심선 교차). |

## 3. 신규 컴포넌트

### 3.1 원시 지표 (`core/indicators.py`)
- `compute_bbw(df, period=20, std_dev=2.0)`: 밴드폭 = `(upper-lower)/mid`
- `compute_percent_b(df, period=20, std_dev=2.0)`: %B = `(close-lower)/(upper-lower)`
- `compute_mfi(df, period=14)`: MFI(거래량 가중 RSI 격) — High/Low/Close/Volume 사용
- `compute_double_pattern(df, band_period=20, band_std=2.0, pivot_lookback=5, volume_mult=1.5)`:
  쌍바닥/쌍봉 이벤트. bullish/bearish 두 컬럼 반환(engulfing과 동일한 패턴)
- `compute_rsi_divergence(df, rsi_period=14, pivot_lookback=5)`: 가격-RSI 다이버전스 이벤트.
  bullish/bearish 두 컬럼 반환

### 3.2 expression 함수 (`core/expression_engine.py`) — "수식" 전략용
- `bbw(close, period, std)`, `percent_b(close, period, std)`, `mfi(high, low, close, volume, period)`
- 쌍바닥/쌍봉·다이버전스는 **expression 함수로 노출하지 않음** — engulfing과 같은 이유(여러 봉에 걸친
  상태형 패턴 탐지라 한 줄 수식의 "그 시점 값 계산"과 성격이 다름). 조건-조합(regime/staged)
  스키마의 지표 옵션으로만 제공.

### 3.3 조건 평가기 (`core/strategy_engine.py` — regime/staged 공용 `INDICATOR_EVALUATORS`)
- `bbw_squeeze_release`: 이벤트. 최근 `lookback`봉 내에 밴드폭이 `threshold` 아래였다가 지금
  다시 위로 크로스오버하면 True, 그 뒤 `hold_bars`봉 동안 유지(같은 봉/며칠 내 돌파 확인을 단일
  조건으로 표현하기 위함). 파라미터: `period`(20), `std_dev`(2.0), `threshold`(0.1, 종목마다
  다르다고 원본이 명시 — `core/strategy_tuning.py`가 `_THRESHOLD_LIKE_KEYS`로 이미 숫자 튜닝
  가능하니 종목별 최적화는 튜닝 엔진에 맡김), `lookback`(20), `hold_bars`(3)
- `percent_b`: 상태. `op`/`value` 비교 (예: `>= 0.8`)
- `mfi`: 상태. `op`/`value` 비교 (예: `>= 80`)
- `bollinger`에 `band="mid"` 추가 — `op="break_above"|"break_below"`로 중심선 상향/하향 돌파
  (기존 upper/lower와 동일한 크로스 판정 방식)
- `double_pattern`: 이벤트. `direction="bullish"|"bearish"` (쌍바닥/쌍봉)
- `rsi_divergence`: 이벤트. `direction="bullish"|"bearish"`

### 3.4 진입가 기준 손절 (신규 일반 메커니즘)

`simulate_staged_positions()`의 `entry_stages`/`exit_stages`와 형제 키로 최상위에 선택적
`"stop_loss"` 필드 추가:

```json
"stop_loss": {"source": "bollinger_mid", "period": 20, "std_dev": 2.0}
"stop_loss": {"source": "lowest_low", "period": 20}
"stop_loss": {"source": "highest_high", "period": 20}
```

동작: 포지션이 없다가(open_tags 비어있음) 처음 진입이 발생한 바("사이클 시작")에서 `source`가
가리키는 **레벨(가격 자체, 불리언 아님)**의 그 날 값을 스냅샷해 고정한다. 이후 그 사이클이
끝날 때까지, 종가가 이 고정된 레벨 아래로 내려오면 emergency_exit과 같은 우선순위로 즉시 전량
청산(`StageEvent(kind="stop_loss")`로 로그). `source`는 지표값을 그대로 반환하는 별도의 작은
레벨-소스 레지스트리(`STOP_LOSS_SOURCES`)로 구현 — 기존 `INDICATOR_EVALUATORS`(불리언 반환)와는
반환 타입이 달라 분리.

**적용 범위**: 이 스퀴즈 전략(중심선 스냅샷)에만 즉시 쓰이지만, 이후 다른 전략에도 재사용 가능한
일반 기능으로 둔다(요청 결정사항 2번).

## 4. 전략별 구현 매핑 (난이도 순)

### 4-1. 스퀴즈 매매 (가장 쉬움)
- 진입: `bbw_squeeze_release(threshold=0.1, lookback=20, hold_bars=3)` AND
  `bollinger(band=upper, op=break_above)`
- 청산(익절): `bollinger(band=mid, op=break_below)`
- 손절: `stop_loss={source: bollinger_mid, period:20}`

### 4-2. 추세추종 (%B + MFI)
- 진입: `percent_b(period=20, std_dev=2, op=">=", value=0.8)` AND `mfi(period=14, op=">=", value=80)`
- 청산(익절): `bollinger(band=mid, op=break_below)`
- 손절: `stop_loss={source: lowest_low, period: 20}` (직전 저점 근사)
- (영상 후반 "예비신호 후 확정신호 2회 확인" 언급은 선택적 강화 옵션으로 별도 언급, 기본 구현에는
  넣지 않음 — 과최적화 방지, 필요하면 후속 요청으로)

### 4-3. 추세반전 (쌍바닥/쌍봉)
- 진입: `double_pattern(direction=bullish)` — 밴드 위치 제약(첫 저점 밴드 밖/둘째 저점 밴드 안)과
  거래량 급증까지 지표 함수 내부에서 전부 판정
- 익절/손절 원문에 명시 없음 → 구현하지 않음(추측으로 추가하지 않음)

### 4-4. 다이버전스 (가장 어려움 — 피벗 탐지 + 추세선 기울기 비교)
- 진입: `rsi_divergence(direction=bullish)` AND `bollinger(band=mid, op=break_above)`
- 손절: `stop_loss={source: lowest_low, period: ...}` (최근 저점)
- 익절(손익비 2:1 분할매도)은 이번 엔진의 "전량 청산" 이분법 구조상 분할 매도까지는 스코프 밖
  (아래 §5에 한계로 명시)

## 5. 스코프에서 제외한 것 (한계 명시)

- **숏(매도) 포지션**: 엔진이 롱온리라 전부 제외.
- **분할 익절(손익비 2:1 도달 시 일부만 매도)**: `simulate_staged_positions`는 청산 단계별로
  "그 단계의 전체 물량"만 정리하는 구조라 "동일 사이클 내 남은 물량의 일부"를 조건부로 파는 개념이
  없음 — 다이버전스 전략의 "손익비 2:1시 분할매도"는 구현하지 않음.
- **추세추종의 "예비신호→확정신호 2회 확인"**: 선택 강화 옵션으로 문서화만 하고 기본 구현에서 제외.

## 6. `core/nl_strategy.py` 반영

향후 유튜브 대본을 붙여넣었을 때 AI가 이 6개 지표(`bbw_squeeze_release`/`percent_b`/`mfi`/
`double_pattern`/`rsi_divergence`/`bollinger band="mid"`)와 `stop_loss` 필드를 쓸 수 있도록
`STAGE_CONDITION_PROPERTIES`/`STAGED_SYSTEM_PROMPT`/`STAGED_INDICATOR_CONFIG_SCHEMA`에 반영.
**겸사겸사 수정**: 지난 세션에 발견된 "지표 타입과 무관한 필드가 섞여 들어가는" 문제(예: bollinger
조건에 일목균형표 파라미터가 붙는 것) 재발 방지를 위해 프롬프트에 "해당 지표에 정의되지 않은 필드는
절대 채우지 말 것" 문구 추가.
