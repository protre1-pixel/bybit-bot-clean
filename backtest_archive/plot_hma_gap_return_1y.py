"""
2026-08-14: HMA200/600 갭임계값 스윕(0.0~2.0%) 결과를 텍스트 표 말고 이미지 그래프로
바로 보여달라는 요청. XRP 15분봉 최근 1개월(30일)치로 임계값별 총수익률(%)을 막대그래프로.
"""
import sys
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False

bcl.SQUEEZE_ENTER_MULT = 0.7
bcl.BREAKOUT_MULT = 1.6

SYMBOL = "XRPUSDT"
INTERVAL = "15"
DAYS = 365
GAP_THRESHOLDS = [0.0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0]

candles = bcl.fetch_klines(SYMBOL, INTERVAL, DAYS)
print(f"[{SYMBOL}] 캔들 {len(candles)}개 "
      f"({bcl.datetime.fromtimestamp(candles[0]['ts']/1000)} ~ {bcl.datetime.fromtimestamp(candles[-1]['ts']/1000)})")

labels, returns, trade_counts, win_rates = [], [], [], []
for gap in GAP_THRESHOLDS:
    trades, final_seed = bcl.run_backtest(candles, use_hma_direction_only=True, hma_gap_min_pct=gap)
    total_return = (final_seed - bcl.SEED) / bcl.SEED * 100
    n = len(trades)
    wr = (len([t for t in trades if t["profit"] > 0]) / n * 100) if n else 0
    labels.append(f"{gap:.2f}%")
    returns.append(total_return)
    trade_counts.append(n)
    win_rates.append(wr)
    print(f"갭>={gap:>5.2f}%  거래수={n:>4}  승률={wr:5.1f}%  수익률={total_return:+6.2f}%")

fig, ax1 = plt.subplots(figsize=(12, 7))
colors = ["#2ecc71" if r >= 0 else "#e74c3c" for r in returns]
bars = ax1.bar(labels, returns, color=colors, width=0.6)
for b, r, n in zip(bars, returns, trade_counts):
    ax1.text(b.get_x() + b.get_width() / 2, r + (0.5 if r >= 0 else -0.5),
              f"{r:+.2f}%\n({n}건)", ha="center",
              va="bottom" if r >= 0 else "top", fontsize=9)

ax1.axhline(0, color="black", linewidth=0.8)
ax1.set_title(f"{SYMBOL} 15분봉 최근 {DAYS}일(1년) - HMA갭 임계값별 총수익률", fontsize=14)
ax1.set_xlabel("HMA200/600 갭 최소임계값")
ax1.set_ylabel("총수익률 (%)")
ax1.grid(alpha=0.25, axis="y")

fig.tight_layout()
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hma_gap_return_1y.png")
plt.savefig(out_path, dpi=130)
print(f"saved: {out_path}")
