import sys, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

candles = bcl.fetch_klines("XRPUSDT", "15", 365)
sizes = np.array([c["high"] - c["low"] for c in candles])
n = len(sizes)
print(f"총 캔들수: {n}")

for lookback, mult in [(30, 2.0), (14, 2.0), (30, 1.6)]:
    hits = 0
    checked = 0
    for idx in range(lookback, n):
        window = sizes[idx-lookback:idx]
        avg = window.mean()
        if avg <= 0:
            continue
        checked += 1
        if sizes[idx] >= avg * mult:
            hits += 1
    print(f"lookback={lookback} mult={mult}: {hits}/{checked} = {hits/checked*100:.2f}% 캔들이 조건 충족(HMA/필터 적용 전, 순수 트리거 발생률)")

# 밴드폭 기준 비교용: 얼마나 자주 스퀴즈(0.7배 미만)가 먼저 발생하는지
width_series = bcl.compute_width_series(candles)
valid = ~np.isnan(width_series)
avg_w = np.nanmean(width_series[valid])
print(f"\n[참고] 밴드폭 시리즈 평균: {avg_w:.6f}, 캔들크기 평균(30lb 기준 마지막 시점): {sizes[-30:].mean():.6f}")

# 캔들 크기 분포 특성 (왜도 확인용 - 평균 대비 median/percentile)
print(f"\n캔들크기(high-low) 분포: mean={sizes.mean():.6f} median={np.median(sizes):.6f} "
      f"p90={np.percentile(sizes,90):.6f} p99={np.percentile(sizes,99):.6f} max={sizes.max():.6f}")
print(f"mean/median 비율: {sizes.mean()/np.median(sizes):.2f} (1보다 많이 크면 오른쪽 꼬리가 두꺼운 분포)")
