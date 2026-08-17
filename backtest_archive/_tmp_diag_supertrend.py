import sys, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

candles = bcl.fetch_klines("XRPUSDT", "15", 365)
st_line, st_dir = bcl.compute_supertrend_series(candles, period=10, multiplier=3.0)
n = len(candles)
valid = ~np.isnan(st_dir)
print(f"총 캔들 {n}, 유효(non-nan) {valid.sum()}, 첫 유효 인덱스 {np.argmax(valid)}")

flips = 0
prev = None
for d in st_dir[valid]:
    if prev is not None and d != prev:
        flips += 1
    prev = d
print(f"방향 플립 횟수(1년): {flips}건  (평균 {valid.sum()/max(flips,1):.1f}캔들당 1회)")

# NaN 구간 이후 st_line이 close 근처에 있는지 sanity check (너무 동떨어지면 버그 의심)
closes = np.array([c["close"] for c in candles])
idx = np.where(valid)[0]
sample_idx = idx[len(idx)//2]
print(f"샘플 idx={sample_idx}: close={closes[sample_idx]:.5f} st_line={st_line[sample_idx]:.5f} dir={st_dir[sample_idx]}")
diffpct = abs(closes[valid] - st_line[valid]) / closes[valid] * 100
print(f"close 대비 st_line 괴리율: mean={diffpct.mean():.3f}% max={diffpct.max():.3f}%")
