"""
2026-08-14: 복리+10배 레버리지 구조에서 "총수익률"로 임계값을 비교하면 거래횟수 차이가
지수적으로 결과를 지배해버려서(0.00%가 428건 복리 vs 2.00%가 126건 복리 → 억 단위로 차이)
비교 자체가 무의미하다는 걸 확인. 대신 복리/레버리지 영향을 제거한
"거래 1건당 평균 수익률(raw_pct, 가격변동 기준 %)"과 "비복리 단순합산 수익률"로
필터 품질을 다시 비교.

XRP 15분봉 1년치(365일), 갭임계값 0.0~2.0%.
"""
import sys
import os
import numpy as np
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

labels, avg_pcts, sum_pcts, trade_counts, win_rates = [], [], [], [], []
for gap in GAP_THRESHOLDS:
    trades, _ = bcl.run_backtest(candles, use_hma_direction_only=True, hma_gap_min_pct=gap)
    n = len(trades)
    pcts = np.array([t["pct"] for t in trades])  # raw_pct*100, 레버리지/수수료 미적용 가격변동%
    avg_pct = pcts.mean() if n else 0
    sum_pct = pcts.sum() if n else 0
    wr = (len([t for t in trades if t["profit"] > 0]) / n * 100) if n else 0
    labels.append(f"{gap:.2f}%")
    avg_pcts.append(avg_pct)
    sum_pcts.append(sum_pct)
    trade_counts.append(n)
    win_rates.append(wr)
    print(f"갭>={gap:>5.2f}%  거래수={n:>4}  승률={wr:5.1f}%  거래당평균={avg_pct:+.3f}%  단순합산={sum_pct:+8.2f}%")

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))

colors1 = ["#2ecc71" if v >= 0 else "#e74c3c" for v in avg_pcts]
bars1 = ax1.bar(labels, avg_pcts, color=colors1, width=0.6)
for b, v, n in zip(bars1, avg_pcts, trade_counts):
    ax1.text(b.get_x() + b.get_width() / 2, v + (0.01 if v >= 0 else -0.01),
              f"{v:+.3f}%\n({n}건)", ha="center", va="bottom" if v >= 0 else "top", fontsize=8)
ax1.axhline(0, color="black", linewidth=0.8)
ax1.set_title("거래 1건당 평균 수익률\n(복리·레버리지 미적용, 가격변동 기준)", fontsize=12)
ax1.set_xlabel("HMA200/600 갭 최소임계값")
ax1.set_ylabel("평균 수익률 (%)")
ax1.grid(alpha=0.25, axis="y")

colors2 = ["#2ecc71" if v >= 0 else "#e74c3c" for v in sum_pcts]
bars2 = ax2.bar(labels, sum_pcts, color=colors2, width=0.6)
for b, v, n in zip(bars2, sum_pcts, trade_counts):
    ax2.text(b.get_x() + b.get_width() / 2, v + (0.5 if v >= 0 else -0.5),
              f"{v:+.1f}%\n({n}건)", ha="center", va="bottom" if v >= 0 else "top", fontsize=8)
ax2.axhline(0, color="black", linewidth=0.8)
ax2.set_title("비복리 단순합산 수익률\n(매 거래 동일 비중 가정, 복리 재투자 없음)", fontsize=12)
ax2.set_xlabel("HMA200/600 갭 최소임계값")
ax2.set_ylabel("합산 수익률 (%)")
ax2.grid(alpha=0.25, axis="y")

fig.suptitle(f"{SYMBOL} 15분봉 최근 {DAYS}일(1년) - HMA갭 임계값별 (복리효과 제거)", fontsize=14)
fig.tight_layout()
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hma_gap_avgpct_1y.png")
plt.savefig(out_path, dpi=130)
print(f"saved: {out_path}")
