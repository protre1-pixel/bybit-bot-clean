import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

SYMBOL = "XRPUSDT"
INTERVAL = "15"
DAYS = 365

bcl.SQUEEZE_ENTER_MULT = 0.7
bcl.BREAKOUT_MULT = 1.6

PLT, PLR = 0.2, 0.85
STALL_CANDLES = 4
STALL_MIN_PEAK = 0.15
STALL_SL_PCT = 0.8
ENTRY_SL_CAP = 1.5

candles = bcl.fetch_klines(SYMBOL, INTERVAL, DAYS)

trades, seed_end = bcl.run_backtest(
    candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
    use_hma_direction_only=True, use_price_alignment_filter=True,
    stall_exit_candles=STALL_CANDLES, stall_exit_min_peak_pct=STALL_MIN_PEAK,
    stall_exit_sl_pct=STALL_SL_PCT, entry_sl_cap_pct=ENTRY_SL_CAP)

tfs = [t for t in trades if t["reason"] == "Trend Follow Stop"]
print(f"Trend Follow Stop 총: {len(tfs)}건")

A = [t for t in tfs if t["peak_pct"] < PLT]
B = [t for t in tfs if t["peak_pct"] >= PLT]
print(f"[A] peak < {PLT}% (profit_lock 미발동): {len(A)}건")
if A:
    a_loss = [t for t in A if t["profit"] <= 0]
    print(f"   손실거래 {len(a_loss)}/{len(A)}  그룹총손익 ${sum(t['profit'] for t in A):.2f}")
print(f"[B] peak >= {PLT}% (profit_lock 발동): {len(B)}건")
if B:
    b_loss = [t for t in B if t["profit"] <= 0]
    print(f"   손실거래 {len(b_loss)}/{len(B)}  그룹총손익 ${sum(t['profit'] for t in B):.2f}")

# stall-exit이 실제로 얼마나 개입했는지: 홀드시간이 1시간(4캔들) 이하인 거래 비중
short_hold = [t for t in trades if t["hold_h"] <= 1.0]
print(f"\n전체 거래 중 보유시간<=1h: {len(short_hold)}/{len(trades)}건 ({len(short_hold)/len(trades)*100:.1f}%)")
sh_loss = [t for t in short_hold if t["profit"] <= 0]
print(f"   그 중 손실: {len(sh_loss)}건  그룹총손익 ${sum(t['profit'] for t in short_hold):.2f}")

print("\n최악 5건 (peak% -> 최종%):",
      sorted([(round(t["peak_pct"],2), round(t["pct"],2)) for t in tfs], key=lambda x: x[1])[:5])
print("=== COMBO DIAG COMPLETE ===")
