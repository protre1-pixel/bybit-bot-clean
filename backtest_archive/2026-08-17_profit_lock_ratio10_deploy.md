# 2026-08-17 profit_lock_ratio 0.85 → 1.0 실전 반영

## 배경

사용자 문의(전 세션에서 이어짐): "지금 테스트에서 제일 베스트가 0.5(trigger)에 1.0(ratio)이었지?
0.5에 0.9도 테스트해서 비교해봐" → ratio 0.9 vs 1.0을 현재 라이브와 동일한 풀 콤보(trigger=0.5%,
stall_exit, fast_breakout, price_alignment_filter, regime_exit 전부 적용) 기준으로 직접 재검증.

## 검증 (`test_profit_lock_ratio09_vs_10_4coin_1y.py`)

BTCUSDT/ETHUSDT/XRPUSDT/SOLUSDT, 15분봉, 365일치.

| 심볼 | ratio | 거래수 | 승률 | PF | MDD | 비복리합산% | 복리(참고) |
|---|---|---|---|---|---|---|---|
| BTC | 0.9 | 236 | 64.0% | 1.16 | 50.9% | +44.9% | +213.86% |
| BTC | **1.0** | 236 | 64.0% | **1.23** | **42.4%** | **+53.6%** | **+481.54%** |
| ETH | 0.9 | 252 | 61.1% | 1.24 | 45.7% | +61.9% | +720.26% |
| ETH | **1.0** | 252 | 61.1% | **1.31** | **44.4%** | **+73.9%** | **+1785.97%** |
| XRP | 0.9 | 228 | 68.9% | 1.43 | 39.1% | +65.3% | +892.72% |
| XRP | **1.0** | 228 | 68.9% | **1.57** | **38.8%** | **+77.1%** | **+2054.62%** |
| SOL | 0.9 | 257 | 64.6% | 1.21 | 48.0% | +63.6% | +678.74% |
| SOL | **1.0** | 257 | 64.6% | **1.29** | **46.4%** | **+76.8%** | **+1845.90%** |

거래수/승률/평균보유시간은 ratio와 무관하게 완전히 동일(같은 캔들에서 청산되는 건 똑같음) -
ratio는 청산 "타이밍"이 아니라 같은 청산 캔들에서 최고수익 대비 얼마를 반납하고 나가느냐만
결정. 4코인 전부 예외 없이 1.0이 0.9보다 PF/MDD/수익률 전부 우세 - 반납을 아예 안 하는 1.0이
구조적으로 항상 유리(8/16 스윕 때 확인된 "ratio가 높을수록 단조 개선" 패턴과 일치).

## 채택 및 캐비어트

사용자 승인 하에 `PROFIT_LOCK_RATIO`를 0.85 → 1.0으로 변경. `PROFIT_LOCK_TRIGGER_PCT`(0.5%)는
그대로 유지.

**리스크**: 15분봉 OHLC는 캔들 내부에서 저가/고가가 어느 순서로 도달했는지 기록하지 않음.
ratio=1.0(반납 쿠션 0%)은 실거래에서 봉단위 백테스트보다 더 자주 손절가에 걸릴 가능성이 있음 -
불리한 방향 반응이 관찰되면 0.9~0.95 사이로 되돌릴 수 있음.

## 배포

- `bybit-bot1`(LIVE)/`bybit-bot2`(DEMO), 서버 192.168.1.134(user protre)에 배포.
- 서버 원본 백업(`trading_service.py.bak_20260817_210622`) 후 `app/services/trading_service.py`
  교체, 양쪽 다 `python3 -m py_compile` 통과 확인.
- `pm2 restart bybit-bot1 bybit-bot2` → 둘 다 online, 에러 없이 정상 기동
  (LIVE: "Bybit API 연결 성공 (LIVE)", DEMO: "Bybit API 연결 성공 (DEMO)" 로그 확인).

## 관련 파일

- `app/services/trading_service.py` — `PROFIT_LOCK_RATIO = 1.0`로 변경, 근거 주석 추가.
- `backtest_archive/backtest_current_live.py` — 이번 세션에 추가한
  `profit_lock_ratio_tier2_pct`/`profit_lock_ratio_tier2` 옵션 포함(하위호환, 기본 None).
- `backtest_archive/test_profit_lock_ratio09_vs_10_4coin_1y.py` — 이번 채택의 직접 근거(4코인 검증).
- `backtest_archive/test_profit_lock_tiered_ratio_4coin_1y.py` — 앞서 tier(구간별 차등 ratio) 실험
  기각 근거(flat 1.0이 모든 tier 조합보다 우세).
- `backtest_archive/test_pure_regime_trail_xrp_1y.py`,
  `backtest_archive/test_regime_trail_after_profit_xrp_1y.py` — "정배열/역배열 유지되는 동안
  무조건 홀드"(순수 regime 트레일링) 및 그 하이브리드 버전을 XRP로 검증했으나 둘 다 MDD
  99.9~100%, 복리 -99.94~-99.99%로 계좌 증발 수준의 결과가 나와 기각(미채택, 참고용으로만 보존).
