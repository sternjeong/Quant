# 캔들스틱 패턴 실전 매매법 구현 스펙 (논의 노트)

> **상태: 구현 완료.** 사용자가 유튜브 캔들차트 강의 대본(마루보즈/핀바/도지/장악형/인사이드바/관통형/
> 모닝스타·이브닝스타/적삼병·흑삼병/삼법형)을 제공하며 "수식을 만들고 전략을 넣어달라"고 요청.
> `BOLLINGER_STRATEGIES_SPEC.md`와 동일한 워크플로(원문 → 수학적 정의 → 지표 함수 → 조건 평가기 →
> 구체 전략)를 그대로 재사용한다.

## 1. 요청 요약

영상은 캔들 패턴 9개 카테고리를 설명한다. 전부 지표(수식)로 구현하되, "손절/익절까지 명시적으로
설명된" 것만 완성된 매매 전략으로 등록한다(추측으로 손절/익절을 지어내지 않음 — Bollinger 스펙과
동일한 원칙).

## 2. 기존 엔진 재사용/제약 확인

| 항목 | 확인 결과 |
|---|---|
| 진입≠청산, 손절 | `entry_stages`/`exit_stages`/`stop_loss`(진입가 기준 손절) 그대로 재사용 가능. |
| 롱온리 | 여전히 롱온리(변경 없음). 영상의 숏 예시(약세 핀바/하락 관통형·흑운형/이브닝스타/흑삼병/하락
  삼법형)는 전부 스코프 제외 — 각 패턴의 지표(수식) 자체는 bullish/bearish 양쪽 다 구현하되(향후
  숏 지원 시 바로 재사용 가능), "완성된 전략"은 롱 사이드만 등록한다. |
| 손익비(R-multiple) 고정 익절 | 없음. 모닝스타 전략이 "손절선 대비 2배 비율 익절"을 명시적으로 요구해
  신규 일반 메커니즘으로 추가(§3.3). |
| 단일 이동평균선 터치/돌파 | 없음(기존 `ma_cross`는 두 선의 교차만 지원). 삼법형 전략의 "20 지수이평선
  터치 시 익절"에 필요해 신규 추가(§3.2). |
| N봉 지지/저항 돌파를 불리언으로 | `compute_highest_high`/`compute_lowest_low`는 손절 레벨 소스로만
  쓰이고 있었음(레벨 값 반환). 장악형 돌파 전략에 "저항선 돌파" 확인 조건이 필요해 이를 불리언
  이벤트로 감싸는 `level_break` 조건 추가(§3.2). |

## 3. 신규 컴포넌트

### 3.1 캔들 패턴 지표 (`core/indicators.py`)

공용 기하 계산 `_candle_geometry(df)` → body(몸통) / range(고가-저가) / upper_wick(위꼬리) /
lower_wick(아래꼬리). 아래 9개 함수 모두 `bullish`/`bearish`(또는 도지는 4개 타입) 컬럼을 가진
DataFrame을 반환하며, `engulfing`/`double_pattern`과 동일한 관례를 따른다.

| 함수 | 수식(핵심 정의) |
|---|---|
| `compute_marubozu(body_ratio_threshold=0.9)` | 몸통/범위 ≥ threshold. 양봉이면 bullish(장대양봉), 음봉이면 bearish(장대음봉). |
| `compute_pin_bar(body_ratio_max=0.3, wick_body_mult=2.0)` | 몸통/범위 ≤ max **AND** 한쪽 꼬리 ≥ 몸통×mult **AND** 반대쪽 꼬리 ≤ 몸통. 아래꼬리 긴 쪽=강세, 위꼬리 긴 쪽=약세. |
| `compute_doji(body_ratio_max=0.1, ...)` | 몸통/범위 ≤ max(도지 판정) 후 위/아래꼬리 비율로 4분류: 잠자리형(아래꼬리만 김, 하락 저점에서 신뢰도 최고)/비석형(위꼬리만 김, 상승 고점에서 신뢰도 최고)/키다리형(양쪽 다 김)/일반. |
| `compute_inside_bar()` | 당일 고가 ≤ 전일 고가 **AND** 당일 저가 ≥ 전일 저가 (마더 바 범위 안에 완전 포함). 방향은 돌파 조건(`level_break`)과 조합해서 표현. |
| `compute_piercing_dark_cloud(band_period=20, band_std=2.0)` | 전일 몸통 중간값(prev_mid)을 파고들되 전일 몸통을 완전히 감싸지는 않는 2봉 패턴. 실전 신뢰도를 위해 볼린저 밴드 이탈→복귀 확인까지 지표 내부에서 판정(영상의 "관통형+볼린저 밴드" 실전 매매법 그대로): 상승 관통형=저가가 하단 밴드 아래로 뚫었다가 종가는 하단 밴드 위로 복귀. |
| `compute_star_pattern(star_body_ratio_max=0.3, big_body_ratio_min=0.5)` | 큰 캔들(1번) → 몸통 작은 별(2번, 갭 발생) → 반대 방향 큰 캔들(3번, 1번 몸통 중간값 이상/이하로 마감)의 3봉 패턴. 모닝스타=상승 반전, 이브닝스타=하락 반전. |
| `compute_three_soldiers_crows(body_ratio_min=0.6)` | 몸통 큰 같은 방향 캔들 3개 연속, 매 캔들이 직전 몸통 안에서 시작하고 종가가 매번 더 멀리 진행. 적삼병=상승/흑삼병=하락. |
| `compute_rising_falling_three_methods(n_pause=3, big_body_ratio_min=0.5)` | 큰 캔들(0번) → 그 범위 안에 완전히 갇힌 조정 캔들 n_pause개 → 0번 종가를 갱신하며 마감하는 마무리 큰 캔들. 상승/하락 삼법형(추세 지속형). |

engulfing(장악형)은 이미 구현되어 있어 재사용만 한다.

### 3.2 조건 평가기 (`core/strategy_engine.py` — `INDICATOR_EVALUATORS`)

위 8개 지표 각각 `direction`(bullish/bearish, 도지는 `doji_type`)로 조건화. 추가로:
- `level_break`: `source`(highest_high/lowest_low, 기본 highest_high) 기준 직전 N봉(당일 제외) 고점/저점을
  `op`(break_above/break_below)로 돌파했는지 판정하는 이벤트. "저항선/지지선 돌파"를 표현하는 범용 조건.
- `ma_touch`: 단일 이동평균선(`period`, `ma_type`=sma/ema)을 종가가 상향/하향 돌파(`op`)하는 이벤트.
  `ma_cross`의 단일선 버전. "20 지수이평선에 닿으면"처럼 단일 이평선 터치 익절 조건에 사용.

### 3.3 손절 대비 배수 익절 (`take_profit`, 신규 일반 메커니즘)

`stop_loss`와 형제 키로 최상위에 선택적 `"take_profit": {"multiple": 2.0}` 추가. `stop_loss`가 반드시
함께 정의되어 있어야 하며(없으면 `ValueError`), 진입 사이클 시작 바에서
`목표가 = 진입참조가 + multiple × (진입참조가 − 손절레벨)`을 스냅샷해 고정한다. 이후 종가가 이 목표가
이상이 되면 emergency_exit/stop_loss와 동일한 우선순위로 즉시 전량 청산(`StageEvent(kind="take_profit")`).
`extract_staged_trades`는 이미 `kind != "entry"`를 전부 청산으로 처리하므로 별도 수정 불필요.

## 4. 전략별 구현 매핑 (영상에 손절/익절까지 명시된 것만 완성 전략으로 등록)

| 전략명 | 진입 | 손절 | 익절 |
|---|---|---|---|
| 강세 핀바 반전 전략 | `pin_bar(bullish)` | 핀바 캔들 저점(`lowest_low period=1`) | 명시 없음 → `level_break(lowest_low, 10, break_below)`를 안전장치로 사용 |
| 상승 장악형 돌파 전략 | `engulfing(bullish)` AND `level_break(highest_high, 20, break_above)`(저항선 돌파) | 장악형 캔들 저점(`lowest_low period=1`) | "하락 장악형(큰 음봉이 직전 양봉을 삼킴)이 뜨면 익절" → `engulfing(bearish)` |
| 상승 관통형 전략 | `piercing_dark_cloud(bullish, band_period=20, band_std=2.0)`(볼린저 밴드 조건까지 지표 내부에 포함) | 패턴 저점(`lowest_low period=1`) | 볼린저 밴드 상단 터치 → `bollinger(band=upper, op=break_above)` |
| 모닝스타 반전 전략 | `star_pattern(bullish)` | 2번째(도지/별) 캔들 저점 근사(`lowest_low period=2`, 3번째 캔들이 대개 그 구간 최저가가 아니므로 근사) | 손절 대비 2배 → `take_profit(multiple=2.0)` |
| 상승 삼법형 전략 | `three_methods(bullish, n_pause=3)` | 마무리 큰 캔들 저점(`lowest_low period=1`) | 20 지수이평선 터치 → `ma_touch(period=20, ma_type=ema, op=break_below)` |

**모닝스타 손절 레벨은 근사치임을 명시**: 정확히는 "2번째 캔들의 저점"인데 손절 레벨 소스는 진입 신호가
뜨는 바(3번째 캔들, 신호일 기준)에서만 스냅샷하므로 `lowest_low(period=2)`(직전 2봉 중 최저가)로
근사한다. 3번째 캔들이 강한 반전 양봉이라 대부분 2번째 캔들이 그 구간의 최저가이므로 실질적으로는
정확히 일치한다.

마루보즈/도지/인사이드바/적삼병·흑삼병은 영상에 손절·익절까지 딸린 완결된 워크스루가 없어(정성적
설명만 있거나, 유일한 워크스루가 숏 방향) **애초에는** 지표(조건)만 제공하고 완성 전략을 등록하지
않았으나, §8-2에서 사용자 요청으로 웹 검색을 통해 보충함.

## 5. 스코프에서 제외한 것

- **숏(매도) 포지션 전부**: 약세 핀바, 하락 관통형(흑운형), 이브닝스타, 흑삼병, 하락 삼법형의 영상
  워크스루는 전부 숏 예시라 완성 전략에서 제외(엔진이 롱온리). 지표 자체는 bearish 컬럼까지 구현되어
  있어 엔진이 숏을 지원하게 되면 바로 재사용 가능.

## 6. `core/nl_strategy.py` 반영

향후 유사한 캔들 패턴 유튜브 대본을 붙여넣었을 때 AI가 이 지표들(`marubozu`/`pin_bar`/`doji`/
`inside_bar`/`inside_bar_breakout`/`piercing_dark_cloud`/`star_pattern`/`three_soldiers_crows`/
`three_methods`/`level_break`/`ma_touch`)와 `take_profit` 필드를 쓸 수 있도록
`STAGE_CONDITION_PROPERTIES`/`STAGED_SYSTEM_PROMPT`/`STAGED_INDICATOR_CONFIG_SCHEMA`/
`_STAGED_HINT_KEYWORDS`에 반영.

## 7. DB 등록

Bollinger 4대 매매법과 달리, 이번엔 영상이 진입/손절/익절을 전부 정확한 수치로 제공해 AI 해석 없이
손검증된 JSON을 바로 만들 수 있었다. 따라서 §4의 5개 전략은 `source="youtube_script"`로 DB에 직접
저장해(1회성 시드 스크립트) 바로 전략 라이브러리에 노출한다.

## 8. 후속: "상승 삼법형 0건" 문의 + 정성적 패턴 웹 검색 보충 (같은 날 후속 요청)

### 8-1. 상승 삼법형이 AAPL 기본(3년) 백테스트에서 0건인 이유

사용자가 상승 삼법형 전략을 AAPL로 백테스트했더니 전부 0(수익률/매매횟수)이 나온다고 문의 →
버그 의심하고 재검증. AAPL/MSFT/TSLA/NVDA/AMZN/GOOGL/META/AMD 8개 종목, 2010~2026(최대 16년)
전체로 `compute_rising_falling_three_methods` 발생 횟수를 직접 세어보니 종목당 0~1회 수준으로
극히 드묾. Thomas Bulkowski의 캔들 패턴 대규모 실증 연구(주식 470만 개 캔들 라인 전수 조사)를
검색해 확인한 결과, 상승 삼법형은 **470만 개 중 102개**만 발견된, 그가 추적하는 103개 캔들 패턴
중 빈도 순위 88위(즉 가장 드문 축)인 패턴임을 확인 — **버그가 아니라 이 패턴 자체가 실제 시장에서
극히 드물게 나타나는 것이 정상**이다. 구현을 느슨하게 바꾸지 않음(인위적으로 신호를 늘리면 원래
정의된 고전 패턴과 달라져 사용자를 오도할 수 있음). 기본 3년 조회 구간 대신 다종목 미세튜닝
기능(여러 종목에 한 번에 적용)으로 관찰하거나, 더 긴 기간으로 조회할 것을 UI 안내로 권장할 만함
(이번 세션에서는 캡션 문구까지는 추가하지 않음 — 후속 요청 시 진행).
(출처: [Bulkowski on the Rising Three Methods Candle Pattern](https://thepatternsite.com/Rising3Methods.html))

### 8-2. 정성적 설명만 있던 4개 패턴을 웹 검색으로 보충해 완성 전략 4개 추가 등록

사용자가 "정성적 설명은 인터넷 검색으로 보충하라"고 요청 → 각 패턴의 표준적인 진입/손절/익절
관례를 검색해 근거를 확보하고 완성 전략으로 등록:

| 전략명 | 진입 | 손절 | 익절 | 출처 |
|---|---|---|---|---|
| 마루보즈 돌파 전략 | `marubozu(bullish)` | 캔들 저점(`lowest_low period=1`) | 손절 거리의 1.5배(마루보즈 몸통 길이×1.5를 목표가로 삼는 통상 관례) → `take_profit(multiple=1.5)` | [LiteFinance](https://www.litefinance.org/blog/for-beginners/how-to-read-candlestick-chart/marubozu-candlestick-pattern/), [ProTradingSchool](https://www.protradingschool.com/marubozu-candlestick-pattern/) |
| 잠자리형 도지 반전 전략 | `doji(doji_type=dragonfly)` | 도지 저점(`lowest_low period=1`) | 손절 거리의 2배(최소 손익비 2:1 권장) → `take_profit(multiple=2.0)` | [FXOpen](https://fxopen.com/blog/en/a-dragonfly-doji-candlestick-pattern-definition-interpretation-and-trading-strategies/), [BullishBears](https://bullishbears.com/dragonfly-doji-candlesticks/) |
| 인사이드바 돌파 전략 | `inside_bar_breakout(bullish, lookback=5)`(신규 지표, 아래 설명) | 마더 바 반대편(저점) 근사(`lowest_low period=6`) | 명시적 배수 없음 → 안전장치 fallback만 | [PriceAction.com](https://priceaction.com/price-action-university/strategies/inside-bar/), [Capital.com](https://capital.com/en-int/learn/trading-strategies/inside-bar-trading-strategy) |
| 적삼병 상승 지속 전략 | `three_soldiers_crows(bullish)`(3번째 캔들 종가, "보수적 진입") | 첫 번째 캔들 저점 근사(`lowest_low period=3`) | 명시적 배수 없음 → 안전장치 fallback만 | [LiteFinance](https://www.litefinance.org/blog/for-beginners/how-to-read-candlestick-chart/three-white-soldiers-pattern/), [TradingSim](https://www.tradingsim.com/blog/three-white-soldiers) |

- **신규 지표 `compute_inside_bar_breakout(df, lookback=5)`**: 기존 `compute_inside_bar`(그날 자체의
  포함 관계만 판정하는 무방향 이벤트)만으로는 "인사이드바 출현 후 나중에(수일 이내) 마더 바 고점을
  돌파하면 진입"이라는 표준 매매법을 표현할 수 없었다 — 인사이드바가 성립하는 그날은 정의상 고가가
  마더 바 고가 이하이므로, `inside_bar` AND `level_break`를 그대로 결합하면 같은 날 두 조건이 동시에
  참이 되는 경우가 존재할 수 없어 **항상 신호가 0건**이 되는 조합상 함정이었다(실제로 만들기 전에
  발견해 피함). `compute_double_pattern`과 같은 "성립 후 N봉 이내 확인" 상태 머신 방식으로 신규 구현.
  `core/strategy_engine.py`에 `inside_bar_breakout` 조건으로 등록, `core/nl_strategy.py` 프롬프트에도
  이 함정을 명시적으로 경고문으로 추가.
- 인사이드바/적삼병 전략은 원문(웹 검색 결과)에 위험관리 원칙(예: "계좌 자본의 1~2%")은 있어도
  구체적인 손익비 숫자는 없어 `take_profit`을 채우지 않음(추측 금지 원칙 유지) — `level_break` 안전장치
  exit만 사용.
- 검증: 8개 지표는 이미 §「검증」에서 실제 데이터로 확인됨. 신규 4개 전략은 AAPL/MSFT/TSLA
  2010~2026으로 `run_backtest` 직접 호출해 전부 매매가 발생하고(마루보즈 19~43건, 도지 2~9건,
  인사이드바 25~49건, 적삼병 0~3건) take_profit/stop_loss 이벤트가 정상적으로 섞여 나오는 것을 확인.
  `tests/test_strategy_engine.py`에 `compute_inside_bar_breakout` 단위 테스트 + 조건 디스패치 테스트
  추가, `pytest tests/ -q` 전체 405개 통과.
