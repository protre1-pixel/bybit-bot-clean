"""
2026-08-14: HMA200/600 갭%(|hma200-hma600|/price*100)가 실제로 어느 정도 벌어진
상태를 뜻하는지 감이 안 온다는 요청에 따라, XRP 실제 차트에 HMA200/600을 같이 그리고
갭% 값을 서브플롯으로 함께 보여주는 시각화.
"""
import sys
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False

SYMBOL = "XRPUSDT"
INTERVAL = "15"
DAYS = 365

candles = bcl.fetch_klines(SYMBOL, INTERVAL, DAYS)
n = len(candles)

# 최근 90일 구간만(15분봉 90일 = 8640개) - 눈으로 보기 좋게
WINDOW_DAYS = 90
window_n = WINDOW_DAYS * 96
start_t = max(bcl.HMA_GAP_SLOW + 150, n - window_n)

times, closes, h200s, h600s, gaps_pct = [], [], [], [], []
for t in range(start_t, n):
    h200 = bcl.hma_at(candles, t, bcl.HMA_GAP_FAST)
    h600 = bcl.hma_at(candles, t, bcl.HMA_GAP_SLOW)
    if h200 is None or h600 is None:
        continue
    price = candles[t]["close"]
    gap_pct = abs(h200["hma"] - h600["hma"]) / price * 100
    times.append(datetime.fromtimestamp(candles[t]["ts"] / 1000))
    closes.append(price)
    h200s.append(h200["hma"])
    h600s.append(h600["hma"])
    gaps_pct.append(gap_pct)

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 9), sharex=True,
                                 gridspec_kw={"height_ratios": [2.5, 1]})

ax1.plot(times, closes, color="#999999", linewidth=0.6, label="가격(종가)")
ax1.plot(times, h200s, color="#e74c3c", linewidth=1.6, label="HMA200 (~2.1일)")
ax1.plot(times, h600s, color="#2980b9", linewidth=1.6, label="HMA600 (~6.25일)")
ax1.set_title(f"{SYMBOL} 15분봉 최근 {WINDOW_DAYS}일 - HMA200 vs HMA600", fontsize=13)
ax1.legend(loc="upper left")
ax1.grid(alpha=0.25)

ax2.plot(times, gaps_pct, color="#8e44ad", linewidth=0.9, label="갭% = |HMA200-HMA600|/가격×100")
for lvl, c in [(0.1, "#bbbbbb"), (0.2, "#999999"), (0.3, "#888888"),
               (0.5, "#f39c12"), (0.75, "#e67e22"), (1.0, "#d35400"),
               (1.5, "#c0392b"), (2.0, "#7f0000")]:
    ax2.axhline(lvl, color=c, linewidth=0.8, linestyle="--", alpha=0.7)
    ax2.text(times[-1], lvl, f" {lvl}%", va="center", fontsize=8, color=c)
ax2.set_ylabel("갭 %")
ax2.set_ylim(0, max(3.0, max(gaps_pct) * 1.05))
ax2.grid(alpha=0.25)
ax2.legend(loc="upper left")

fig.autofmt_xdate()
plt.tight_layout()
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hma_gap_visual.png")
plt.savefig(out_path, dpi=130)
print(f"saved: {out_path}")

# 갭% 분포 요약도 같이 출력
arr = np.array(gaps_pct)
print(f"갭% 통계 (최근 {WINDOW_DAYS}일, n={len(arr)}): "
      f"평균 {arr.mean():.3f}%  중앙값 {np.median(arr):.3f}%  최대 {arr.max():.3f}%")
for lvl in [0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0]:
    pct_above = (arr >= lvl).mean() * 100
    print(f"  갭 >= {lvl:>4.2f}% 인 시점 비율: {pct_above:5.1f}%")
