import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

bcl.SQUEEZE_ENTER_MULT = 0.7
bcl.BREAKOUT_MULT = 1.6
candles = bcl.fetch_klines("XRPUSDT", "15", 365)
trades, seed_end = bcl.run_backtest(
    candles, profit_lock_trigger_pct=0.5, profit_lock_ratio=0.85,
    use_hma_direction_only=True, use_price_alignment_filter=True)

tfs = [t for t in trades if t["reason"] == "Trend Follow Stop"]
print("Trend Follow Stop 거래수:", len(tfs))

# profit_lock 트리거(0.5%)에 도달했었는지 여부로 분류
never_locked = [t for t in tfs if t["peak_pct"] < 0.5]
locked = [t for t in tfs if t["peak_pct"] >= 0.5]

print(f"\n[A] peak가 0.5% 미만이었던 거래 (profit_lock 발동 전 = 원래 넓은 SL 그대로): {len(never_locked)}건")
if never_locked:
    avg_pct_a = sum(t["pct"] for t in never_locked)/len(never_locked)
    avg_peak_a = sum(t["peak_pct"] for t in never_locked)/len(never_locked)
    losers_a = [t for t in never_locked if t["pct"] < 0]
    print(f"   평균 peak {avg_peak_a:+.3f}%  평균 실현손익 {avg_pct_a:+.3f}%  손실거래 {len(losers_a)}/{len(never_locked)}건")
    worst_a = sorted(never_locked, key=lambda t: t["pct"])[:5]
    print("   최악 5건 (peak% -> 실현%):", [(round(t['peak_pct'],2), round(t['pct'],2)) for t in worst_a])

print(f"\n[B] peak가 0.5% 이상 찍어서 profit_lock이 걸렸던 거래: {len(locked)}건")
if locked:
    avg_pct_b = sum(t["pct"] for t in locked)/len(locked)
    avg_peak_b = sum(t["peak_pct"] for t in locked)/len(locked)
    losers_b = [t for t in locked if t["pct"] < 0]
    giveback = [(t["peak_pct"] - t["pct"]) for t in locked]
    avg_giveback = sum(giveback)/len(giveback)
    print(f"   평균 peak {avg_peak_b:+.3f}%  평균 실현손익 {avg_pct_b:+.3f}%  손실거래 {len(losers_b)}/{len(locked)}건")
    print(f"   평균 반납폭(peak-실현) {avg_giveback:+.3f}%p")
    worst_b = sorted(locked, key=lambda t: t["pct"])[:5]
    print("   최악 5건 (peak% -> 실현%):", [(round(t['peak_pct'],2), round(t['pct'],2)) for t in worst_b])

total_pnl_a = sum(t["profit"] for t in never_locked)
total_pnl_b = sum(t["profit"] for t in locked)
print(f"\n[A] 그룹 총손익 $: {total_pnl_a:+.2f}")
print(f"[B] 그룹 총손익 $: {total_pnl_b:+.2f}")
