# -*- coding: utf-8 -*-
# 2026-08-07: 상단밴드가격 - 하단밴드가격 = 차이가격(실제 가격 단위) 표.
# bollinger_at()이 이미 라이브와 동일한 BB(period=30, ddof=0) 계산이므로
# upper/lower를 직접 뽑아서 실가격 차이로 보여준다.
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
import backtest_bb_squeeze as bt

KST = timezone(timedelta(hours=9))

candles = bt.fetch_klines("XRPUSDT", bt.INTERVAL, 3)
print(f"총 캔들 {len(candles)}개, 마지막: {datetime.fromtimestamp(candles[-1]['ts']/1000, KST)}")

start = datetime(2026, 8, 6, 18, 0, 0, tzinfo=KST)
start_ts = int(start.timestamp() * 1000)


def bollinger_bands_at(candles, t, period=bt.BB_PERIOD):
    """bt.bollinger_at()과 동일 로직이되, 과거 확정 캔들 표용이므로 라이브의
    '마지막 캔들은 미완성이라 한 칸 당겨쓴다'(-2) 지연을 넣지 않고 candles[t] 자신
    기준(-1)으로 계산한다. (이 지연을 안 빼면 표의 모든 값이 캔들 1개(15분)만큼
    실제 차트보다 밀려서 라벨링된다.)"""
    limit = max(period + 50, 100)
    lo = max(0, t - limit + 1)
    window = candles[lo:t + 1]
    if len(window) < period + 1:
        return None
    close = pd.Series([c["close"] for c in window])
    sma = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    upper = sma + 2 * std
    lower = sma - 2 * std
    idx = len(close) - 1
    if idx < 0 or pd.isna(sma.iloc[idx]):
        return None
    return {"upper": float(upper.iloc[idx]), "lower": float(lower.iloc[idx]),
            "close": window[-1]["close"]}


rows = []
for t in range(len(candles)):
    ts = candles[t]["ts"]
    if ts < start_ts:
        continue
    bb = bollinger_bands_at(candles, t)
    if bb is None:
        continue
    diff = bb["upper"] - bb["lower"]
    kst_time = datetime.fromtimestamp(ts / 1000, KST)
    rows.append((kst_time, bb["upper"], bb["lower"], diff, bb["close"]))

out_lines = []
def emit(s=""):
    print(s)
    out_lines.append(s)

emit(f"\n{'시각':^14} {'상단밴드':>10} {'하단밴드':>10} {'차이가격':>10} {'종가':>10}")
for kst_time, upper, lower, diff, close in rows:
    emit(f"{kst_time.strftime('%m-%d %H:%M'):^14} {upper:>10.4f} {lower:>10.4f} {diff:>10.4f} {close:>10.4f}")

with open("xrp_band_price_table_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))
