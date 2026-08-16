"""
2026-08-16: 청산 타이트닝을 제안하기 전에, 지금 베스트 조합(sq=0.7/bo=1.6 + fast_breakout
믹스 + hma_direction_only + price_alignment_filter, profit_lock 0.5%/0.85%)이 실제로
"최고수익 대비 얼마나 반납하고 있는지"를 먼저 진단. 반납이 크지 않으면 타이트닝은
득보다 실(추세 조기이탈)이 클 수 있음.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

SYMBOL = "XRPUSDT"
INTERVAL = "15"
DAYS = 365

bcl.SQUEEZE_ENTER_MULT = 0.7
bcl.BREAKOUT_MULT = 1.6
PLT, PLR = 0.5, 0.85

candles = bcl.fetch_klines(SYMBOL, INTERVAL, DAYS)
trades, seed_end = bcl.run_backtest(
    candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
    use_hma_direction_only=True, use_price_alignment_filter=True,
    use_fast_breakout=True, fast_breakout_lookback=2, fast_breakout_mult=None)

print(f"총 거래수: {len(trades)}건\n")

# giveback = peak_pct - 실현pct (양수면 최고점 대비 그만큼 반납했다는 뜻, 음수면 -1을 최저점까지 더 밀린것)
tfs = [t for t in trades if t["reason"] == "Trend Follow Stop"]
print(f"Trend Follow Stop 거래: {len(tfs)}건")

buckets = {"peak<0.5%": [], "0.5~1%": [], "1~2%": [], "2%+": []}
for t in tfs:
    p = t["peak_pct"]
    if p < 0.5:
        buckets["peak<0.5%"].append(t)
    elif p < 1.0:
        buckets["0.5~1%"].append(t)
    elif p < 2.0:
        buckets["1~2%"].append(t)
    else:
        buckets["2%+"].append(t)

print("\n| peak구간 | 건수 | 평균peak% | 평균실현% | 평균반납%p | 반납액합계$ | 실현손익합계$ |")
print("|---|---|---|---|---|---|---|")
total_giveback_pct = 0.0
total_giveback_usd_est = 0.0
for label, grp in buckets.items():
    if not grp:
        print(f"| {label} | 0 | - | - | - | - | - |")
        continue
    avg_peak = sum(t["peak_pct"] for t in grp) / len(grp)
    avg_real = sum(t["pct"] for t in grp) / len(grp)
    avg_giveback = avg_peak - avg_real
    sum_profit = sum(t["profit"] for t in grp)
    # 반납액 추정: notional 정보 없으니 profit/pct*giveback으로 근사(선형 가정, raw_pct 기준이라 근사치)
    print(f"| {label} | {len(grp)} | {avg_peak:+.3f}% | {avg_real:+.3f}% | {avg_giveback:+.3f}%p | - | ${sum_profit:+.2f} |")

print("\n[전체 Trend Follow Stop 반납 상세]")
all_giveback = [(t["peak_pct"] - t["pct"]) for t in tfs]
print(f"평균 반납폭: {sum(all_giveback)/len(all_giveback):+.3f}%p")
print(f"반납폭 중앙값: {sorted(all_giveback)[len(all_giveback)//2]:+.3f}%p")
print(f"반납폭 최대: {max(all_giveback):+.3f}%p")

big_peak = [t for t in tfs if t["peak_pct"] >= 1.5]
print(f"\npeak_pct >= 1.5%인 거래: {len(big_peak)}건")
for t in sorted(big_peak, key=lambda x: -x["peak_pct"])[:15]:
    print(f"  peak {t['peak_pct']:+.2f}% -> 실현 {t['pct']:+.2f}%  (반납 {t['peak_pct']-t['pct']:+.2f}%p)  profit ${t['profit']:+.2f}")

print(f"\n전체 거래 profit 합계: ${sum(t['profit'] for t in trades):+.2f}")
print(f"Trend Follow Stop profit 합계: ${sum(t['profit'] for t in tfs):+.2f}")
