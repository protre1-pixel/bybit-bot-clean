"""
2026-08-10 v5 후속: profit_lock ratio 0.4~0.6 스윕에서 12번 비교(4코인x3트리거) 전부
ratio=0.6이 제일 좋은 단조 패턴 확인. 변곡점(너무 타이트해지면 다시 나빠지는 지점) 찾기 위해
trigger=2.0% 고정하고 ratio만 0.6~0.9로 촘촘하게 스윕.
"""
import sys
from backtest_current_live import fetch_klines, run_backtest, summarize, SEED, INTERVAL

DAYS = 400
COINS = ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]
TRIGGER = 2.0
RATIOS = [0.9, 0.93, 0.95, 0.97, 0.99]

for sym in COINS:
    print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 {INTERVAL}분봉 데이터 수집 중...", flush=True)
    candles = fetch_klines(sym, INTERVAL, DAYS)
    print(f"캔들 {len(candles)}개 수집 완료", flush=True)

    for ratio in RATIOS:
        trades, final_seed = run_backtest(candles, profit_lock_trigger_pct=TRIGGER, profit_lock_ratio=ratio)
        summarize(f"{sym} profit_lock trigger={TRIGGER}% ratio={ratio}", trades, final_seed)

print("\n\n=== FINETUNE COMPLETE ===", flush=True)
