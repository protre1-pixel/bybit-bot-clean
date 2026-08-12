"""내일(2026-08-13~) 백테스트 빠르게 돌리려고 미리 캐시 채워두는 스크립트.
XRP/BTC/ETH/SOL x (1시간봉/15분봉) x 1년(365일)치를 미리 받아서 kline_cache/에 파일로 저장.
fetch_klines()가 자동으로 캐시하므로 그냥 한 번씩 호출만 하면 됨. 캐시 유효기간 14일로
늘려놨으니 내일 다시 실행해도 이 파일들 그대로 재사용됨.

사용법: python prefetch_klines.py
"""
import time

import backtest_current_live as bcl

COINS = ["XRPUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT"]
INTERVALS = [("60", "1시간봉"), ("15", "15분봉")]
DAYS = 365

if __name__ == "__main__":
    for sym in COINS:
        for interval, label in INTERVALS:
            t0 = time.time()
            candles = bcl.fetch_klines(sym, interval, DAYS)
            print(f"[{sym}] {label} {DAYS}일치 - 캔들 {len(candles)}개 "
                  f"({time.time()-t0:.1f}초, 캐시됨)", flush=True)
    print("\n=== PREFETCH COMPLETE ===", flush=True)
