# 2026-08-17 정배열(regime) 기반 0단계 청산으로 실전 반영

## 배경

사용자가 실거래 진입 빈도가 느린 것 같다는 문제제기 → "진입 완화(sq/bo 파라미터 조정)" 방향과
"청산 로직 자체를 바꾸는" 방향 두 가지를 순서대로 검증. 최종적으로 진입 완화는 전부 기각하고,
청산 로직 교체(`use_regime_exit=True`)만 채택해서 실전에 반영함.

핵심 아이디어(사용자 제안): "지금 추세(HMA200/600 정배열)가 유지되면 가격이 200일선에 닿아도
버티는 로직(`use_regime_exit`)이 있는데, 이걸 쓰면 진입 시점에 가격이 어디 있든(눌림목이든 아니든)
정배열 방향으로만 들어가고 쭉 가도 되지 않냐"는 문제제기에서 출발. 조사 결과 원래 진입필터
(`use_price_alignment_filter`, 가격까지 완전정배열이어야 진입)은 "0단계 하드청산이 가격vsHMA200
단순교차라서, 눌림목으로 진입하면 진입 직후 바로 걸려 즉시손절되는 문제"를 막기 위한 장치였는데,
`use_regime_exit=True`를 쓰면 그 하드청산 기준 자체가 "정배열이 뒤집히는 순간"으로 바뀌므로
진입필터를 켜둘 이유가 약해질 수 있다는 가설 → 실제로 검증.

모든 테스트: XRPUSDT(주 검증) + BTC/ETH/SOL(일반화 검증), 15분봉, 365일치, 방향판정
(`use_hma_direction_only=True`)/profit_lock/HMA갭 트레일링/stall_exit/fast_breakout 등 나머지
스택은 라이브 그대로 고정. sq/bo는 별도 명시 없으면 라이브 기본값(`SQUEEZE_ENTER_MULT=0.7`,
`BREAKOUT_MULTIPLIER=1.6`) 고정.

---

## 1. 기각된 방향 ①: 진입 완화 (sq/bo 파라미터 스윕)

라이브 대비 진입 문턱을 낮춰서(스퀴즈/브레이크아웃 조건을 느슨하게) 거래 빈도를 늘려보는 방향.
전부 XRP 기준 PF/MDD가 악화되는 동일한 패턴 확인 후 기각.

| 스크립트 | 조합 | 거래수 | 승률 | PF | MDD | 비복리합산% |
|---|---|---|---|---|---|---|
| `test_squeeze_bo_xrp_1y.py` | LIVE(sq0.7/bo1.6) | 231 | 63.2% | 1.35 | 37.6% | +56.0% |
| " | TEST(sq0.5/bo1.5) | 195 | 62.1% | 1.26 | 53.2% | +46.9% |
| `test_squeeze_loosen_xrp_1y.py` | TEST(sq0.8/bo1.6) | 267 | ~63% | 1.27 | 48.5% | +60.7% |
| " | TEST(sq0.9/bo1.6) | 285 | ~63% | 1.25 | 49.9% | +64.1% |
| `test_breakout_loosen_xrp_1y.py` | bo=1.4(sq0.7) | 300 | 63.0% | 1.31 | 46.4% | +82.7% |
| `test_sq_bo14_xrp_1y.py` | sq0.8~1.0 + bo1.4 | 340~387 | 61.8~62.9% | 1.18~1.23 | 43.2~50.2% | +87.7~95.6% |

`bo=1.4`가 XRP 단독으로는 제일 유망해 보였으나, 4코인(BTC/ETH/XRP/SOL)으로 일반화 검증한 결과
(`test_breakout_loosen_4coin_1y.py`) BTC PF가 1.10→**0.96**(복리 -21.02%로 손실 전환), ETH MDD가
40.3%→**73.7%**로 폭증해서 XRP 특정 구간(2025-10) 과적합으로 판정, 기각.

**결론**: 진입 완화 방향은 거래수/비복리합산%는 늘지만 PF/MDD(위험조정 성과)가 예외 없이
악화되는 트레이드오프 — 채택하지 않음.

---

## 2. 기각된 방향 ②: 진입필터(`use_price_alignment_filter`) 제거

`test_no_price_align_regime_exit_xrp_1y.py` — 4가지 조합 비교 (XRP, 365일):

| | A) LIVE | B) REGIME_EXIT만 | C) NO_ALIGN만 | D) NO_ALIGN+REGIME_EXIT |
|---|---|---|---|---|
| align 필터 | O | O | X | X |
| regime_exit | X | O | X | O |
| 거래수 | 231 | 228 | 489 | 476 |
| 승률 | 63.2% | 68.9% | **50.9%** | 64.5% |
| PF | 1.35 | 1.36 | **0.96** | 1.10 |
| MDD | 37.6% | 39.7% | **79.0%** | 58.1% |
| 비복리합산% | +56.0% | +59.3% | +59.6% | +82.8% |
| 복리(참고용) | +427.37% | +571.71% | **-32.22%** | +272.68% |
| HMA200 Break 비중 | 18.6% | 0% | 60.5% | 0.4% |

- C(진입필터만 제거)는 원래 우려대로 완전히 붕괴(PF 0.96, 복리 -32.22%) — 진입필터는 단순
  "즉시손절 방지용"이 아니라 실질적인 진입 품질 필터였음이 재확인됨.
- D(진입필터 제거 + regime_exit)는 C보다는 크게 개선되지만(사용자 가설이 방향은 맞았음을
  시사), 그래도 B(진입필터 유지 + regime_exit만) 대비 모든 위험조정 지표(승률/PF/MDD)에서
  뒤처짐.

**결론**: 진입필터는 그대로 유지, 청산 로직만 교체하는 B안이 가장 견고함.

---

## 3. 채택 방향: `use_regime_exit=True` 단독 반영

### 무엇이 바뀌나

- **기존(0단계 normal 하드청산)**: 현재가가 포지션 반대방향으로 **HMA200을 단순 교차**하면
  즉시 청산("HMA200 Break"). 인트라바 가격 하나로 판정 — 정상적인 눌림목에도 자주 휩소 손절됨.
- **변경 후**: **HMA200 vs HMA600 정배열(regime) 자체**가 포지션에 불리한 방향으로 뒤집히는
  순간에만 청산(캔들 종가 기준, `get_htf_trend()` 재사용). 추세(정배열)가 살아있는 동안은
  가격이 200일선에 잠깐 닿아도(눌림목) 버팀.
- 나머지는 전부 동일 유지: 진입 신호(스퀴즈→브레이크아웃)/진입필터(`use_price_alignment_filter`,
  완전정배열이어야 진입)/1단계 `trend_follow` 전환 조건/HMA갭 40% 수축 트레일링/profit_lock
  래칫/stall_exit/fast_breakout — 전부 라이브 그대로.

### 4코인 1년 검증 (`test_regime_exit_4coin_1y.py`)

| Coin | 변형 | 거래수 | 승률 | PF | MDD | 비복리합산% | 복리(참고용) |
|---|---|---|---|---|---|---|---|
| BTC | BASELINE | 236 | 61.4% | 1.10 | 57.8% | +38.7% | +104.31% |
| BTC | REGIME_EXIT | 236 | 64.0% | 1.12 | 55.0% | +40.5% | +130.19% |
| ETH | BASELINE | 253 | 58.9% | 1.20 | 40.3% | +51.4% | +292.46% |
| ETH | REGIME_EXIT | 252 | 61.1% | 1.20 | 46.4% | +55.9% | +439.51% |
| XRP | BASELINE | 231 | 63.2% | 1.35 | 37.6% | +56.0% | +427.37% |
| XRP | REGIME_EXIT | 228 | 68.9% | 1.36 | 39.7% | +59.3% | +571.71% |
| SOL | BASELINE | 260 | 60.4% | 1.15 | 44.8% | +50.9% | +218.58% |
| SOL | REGIME_EXIT | 257 | 64.6% | 1.17 | 48.9% | +56.9% | +391.17% |

4개 코인 전부 승률 상승, PF 유지 또는 개선, 비복리합산% 개선. MDD는 3/4 코인에서 소폭 상승
(BTC는 오히려 개선) — 대체로 견고하게 일반화되는 개선으로 판단, 채택 확정.

---

## 4. 실전 코드 반영

`app/services/trading_service.py`의 0단계(normal) 하드청산 블록을 교체:

- 기존: `calculate_hma(symbol, period=200, ...)` 단일값으로 가격과 비교, 전용 캐시
  `htf_trend_cache` 사용.
- 변경: `get_htf_trend(symbol, fast_period=200, slow_period=600, timeframe=SQUEEZE_TIMEFRAME)`로
  정배열 방향(`align_trend`)을 계산 — 바로 아래 있는 "단계 전환 판단" 블록이 이미 같은 함수를
  같은 목적(정배열 확인)으로 호출하고 있었으므로, 캐시(`hma_align_cache`)와 계산을 두 블록이
  공유하도록 병합(중복 HMA 계산 제거). `htf_trend_cache`는 더 이상 사용하지 않음.
- 청산 조건: `align_trend`가 포지션 방향에 불리하면(롱인데 역배열, 숏인데 정배열)
  `close_trade(..., "HMA200 Break", ...)`로 즉시 청산 — 종료사유 라벨은 기존과 동일하게 유지
  (통계 비교 편의를 위해 이름은 안 바꿈, 실제 판정 로직만 교체).
- 그 외 진입필터/1단계 전환조건/trend_follow SL 로직은 전혀 수정하지 않음.

## 5. 배포

- `bybit-bot1`(LIVE)/`bybit-bot2`(DEMO) 양쪽에 서버 원본 백업(`trading_service.py.bak_<timestamp>`)
  후 수정 파일 배포, `python3 -m py_compile`로 서버에서도 재확인.
- `pm2 restart bybit-bot1 bybit-bot2` 실행 → 둘 다 정상 기동 확인(에러 없음, Bybit API 연결 성공
  로그 확인).
- 커밋/푸시: 이 파일 및 관련 백테스트 스크립트/결과와 함께 `origin/master`에 반영.

## 관련 파일

- `app/services/trading_service.py` — 실전 반영 코드 본체
- `backtest_archive/backtest_current_live.py` — `use_regime_exit`, `use_price_alignment_filter`
  옵션 포함 백테스트 엔진
- `backtest_archive/test_regime_exit_4coin_1y.py` — 최종 채택 근거(4코인 검증)
- `backtest_archive/test_no_price_align_regime_exit_xrp_1y.py` — 진입필터 제거 대안 기각 근거
- `backtest_archive/test_breakout_loosen_4coin_1y.py`,
  `backtest_archive/test_sq_bo14_xrp_1y.py` 등 — 진입 완화 방향 기각 근거
