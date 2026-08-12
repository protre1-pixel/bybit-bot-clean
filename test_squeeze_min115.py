# -*- coding: utf-8 -*-
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from datetime import datetime
import backtest_bb_squeeze as bt

SYMBOL = "XRPUSDT"
DAYS = 100

out_lines = []
def emit(s=""):
    print(s)
    out_lines.append(s)

candles = bt.fetch_klines(SYMBOL, bt.INTERVAL, DAYS)
emit(f"{SYMBOL} 캔들 {len(candles)}개 ({datetime.fromtimestamp(candles[0]['ts']/1000)} ~ {datetime.fromtimestamp(candles[-1]['ts']/1000)})")

configs = [
    # label, breakout_mode, squeeze_mult, use_adx
    ("baseline: squeeze_avg(누적평균) 1.5x + ADX/DI", "squeeze_avg", 1.5, True),
    ("squeeze(최저점) 1.5x, 필터없음", "squeeze", 1.5, False),
    ("squeeze(최저점) 1.5x, ADX/DI", "squeeze", 1.5, True),
    ("squeeze(최저점) 1.15x, 필터없음", "squeeze", 1.15, False),
    ("squeeze(최저점) 1.15x, ADX/DI", "squeeze", 1.15, True),
    ("squeeze(최저점) 1.3x, 필터없음", "squeeze", 1.3, False),
    ("squeeze(최저점) 1.3x, ADX/DI", "squeeze", 1.3, True),
]

for label, mode, mult, use_adx in configs:
    trades, seed = bt.run_backtest(candles, breakout_mode=mode, tp_mode="frozen",
                                    sl_first=True, use_adx_filter=use_adx, squeeze_mult=mult)
    n = len(trades)
    if n == 0:
        emit(f"[{label}] 거래 없음")
        continue
    wins = [t for t in trades if t["profit"] > 0]
    wr = len(wins) / n * 100
    gw = sum(t["profit"] for t in wins)
    gl = -sum(t["profit"] for t in trades if t["profit"] <= 0)
    pf = gw / gl if gl > 0 else float("inf")
    ret = (seed - bt.SEED) / bt.SEED * 100
    curve = [bt.SEED]
    s = bt.SEED
    for t in trades:
        s += t["profit"]
        curve.append(s)
    peak = curve[0]
    mdd = 0
    for v in curve:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak * 100)
    emit(f"[{label}] 거래{n:3d} 승률{wr:5.1f}% PF{pf:5.2f} 수익률{ret:+7.2f}% MDD{mdd:5.1f}%")

with open("test_squeeze_min115_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))
