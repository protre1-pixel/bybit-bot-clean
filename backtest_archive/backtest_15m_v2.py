"""2026-08-11 실험 재검증: backtest_15m.py / backtest_gap_exit.py에서 profit_lock_trigger_pct/
profit_lock_ratio를 안 넘겨서(기본값 None=비활성) "1시간봉(현재라이브)" baseline이 실제
라이브(PROFIT_LOCK_TRIGGER_PCT=2.0, PROFIT_LOCK_RATIO=0.85 항상 적용)와 달랐던 문제를
바로잡아서 재검증.

15분봉 전체 복귀 + (기존 HMA200 Break / 신규 HMA갭크로스) 두 방식 모두, profit_lock을
정확히 넣은 상태로 1시간봉(현재라이브 정확재현)과 비교.

사용법: python backtest_15m_v2.py [SYMBOL] [DAYS] [SYMBOL2 ...]
"""
import sys
from datetime import datetime

from backtest_current_live import fetch_klines, run_backtest, summarize, DAYS
from backtest_gap_exit import run_backtest_gap_exit

PLT, PLR = 2.0, 0.85  # 현재 라이브 profit_lock 값

if __name__ == "__main__":
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]

    for sym in coins:
        for interval, label in [("15", "15분봉"), ("60", "1시간봉")]:
            print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 {label} 데이터 수집 중...", flush=True)
            candles = fetch_klines(sym, interval, DAYS)
            print(f"캔들 {len(candles)}개 수집 완료 "
                  f"({datetime.fromtimestamp(candles[0]['ts']/1000)} ~ {datetime.fromtimestamp(candles[-1]['ts']/1000)})",
                  flush=True)

            trades_base, seed_base = run_backtest(candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR)
            summarize(f"{sym} {label} 기존(HMA200 Break)+profit_lock", trades_base, seed_base)

            trades_gap, seed_gap = run_backtest_gap_exit(candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR)
            summarize(f"{sym} {label} 신규(HMA갭크로스)+profit_lock", trades_gap, seed_gap)

    print("\n\n=== 15M/GAP-EXIT RECHECK (profit_lock 정확반영) COMPLETE ===", flush=True)
