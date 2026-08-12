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
emit("(live_staging=True: 라이브 4단계 계단식 SL 그대로 재현 / False: 기존 단순 2단계, 참고용)")
emit("")

configs = [
    # label, breakout_mode, squeeze_mult, use_adx, live_staging
    ("baseline: squeeze_avg 1.5x + ADX/DI, live_staging=False(기존)", "squeeze_avg", 1.5, True, False),
    ("baseline: squeeze_avg 1.5x + ADX/DI, live_staging=True(신규)", "squeeze_avg", 1.5, True, True),
    ("squeeze(최저점) 1.15x + ADX/DI, live_staging=False(기존)", "squeeze", 1.15, True, False),
    ("squeeze(최저점) 1.15x + ADX/DI, live_staging=True(신규)", "squeeze", 1.15, True, True),
]

for label, mode, mult, use_adx, live_staging in configs:
    trades, seed = bt.run_backtest(candles, breakout_mode=mode, tp_mode="frozen",
                                    sl_first=True, use_adx_filter=use_adx, squeeze_mult=mult,
                                    live_staging=live_staging)
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
    # exit reason breakdown (live_staging일 때 stage별 얼마나 도달했는지 확인용)
    reason_counts = {}
    for t in trades:
        reason_counts[t["reason"]] = reason_counts.get(t["reason"], 0) + 1
    reason_str = ", ".join(f"{k}:{v}" for k, v in sorted(reason_counts.items()))
    emit(f"[{label}]")
    emit(f"  거래{n:3d} 승률{wr:5.1f}% PF{pf:5.2f} 수익률{ret:+7.2f}% MDD{mdd:5.1f}%")
    emit(f"  청산사유: {reason_str}")
    emit("")

with open("test_live_staging_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))
