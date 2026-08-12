# -*- coding: utf-8 -*-
# 2026-08-07: staged_sl 팬텀체결 버그 수정 후, Stage1 buffer 스윕을 재검증.
# 버그가 진짜 원인이었다면 buf > trigger(1.5) 구간에서 더 이상 무한정 개선되지 않고
# buf=trigger 근처에서 결과가 "평평해져야"(clamp되어 실질적으로 동일해져야) 정상.
import io, sys, bisect
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np
from datetime import datetime
import backtest_bb_squeeze as bt

SYMBOL = "XRPUSDT"
DAYS_15M = 100
DAYS_1H = 160


def hma_series(values, period):
    half = period // 2
    sq = int(np.sqrt(period))
    wma1 = bt.wma(values, half)
    wma2 = bt.wma(values, period)
    diff = 2 * wma1 - wma2
    return bt.wma(diff, sq)


def build_htf_trend_fn(htf_candles, hma200, hma600, interval_ms):
    ts_list = [c["ts"] for c in htf_candles]

    def fn(ts):
        idx = bisect.bisect_right(ts_list, ts) - 1
        while idx >= 0 and ts_list[idx] + interval_ms > ts:
            idx -= 1
        if idx < 0:
            return None
        h2, h6 = hma200[idx], hma600[idx]
        if np.isnan(h2) or np.isnan(h6):
            return None
        if h2 > h6:
            return "up"
        elif h2 < h6:
            return "down"
        return None

    return fn


def stats(trades):
    n = len(trades)
    if n == 0:
        return None
    seed = bt.SEED
    wins = [t for t in trades if t["profit"] > 0]
    wr = len(wins) / n * 100
    gw = sum(t["profit"] for t in wins)
    gl = -sum(t["profit"] for t in trades if t["profit"] <= 0)
    pf = gw / gl if gl > 0 else float("inf")
    curve = [seed]
    s = seed
    for t in trades:
        s += t["profit"]
        curve.append(s)
    ret = (s - seed) / seed * 100
    peak = curve[0]
    mdd = 0
    for v in curve:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak * 100)
    reason_counts = {}
    for t in trades:
        reason_counts[t["reason"]] = reason_counts.get(t["reason"], 0) + 1
    return n, wr, pf, ret, mdd, reason_counts


candles_15m = bt.fetch_klines(SYMBOL, "15", DAYS_15M)
candles_1h = bt.fetch_klines(SYMBOL, "60", DAYS_1H)
close_1h = np.array([c["close"] for c in candles_1h])
hma200_1h = hma_series(close_1h, 200)
hma600_1h = hma_series(close_1h, 600)
htf_fn_1h = build_htf_trend_fn(candles_1h, hma200_1h, hma600_1h, 3600 * 1000)

orig = dict(
    STAGE1_TRIGGER_PCT=bt.STAGE1_TRIGGER_PCT,
    STAGE1_FEE_BUFFER_PCT=bt.STAGE1_FEE_BUFFER_PCT,
    STAGE2_LOCK_RATIO=bt.STAGE2_LOCK_RATIO,
)

print("Stage1 trigger=1.5 고정, lock=0.3 고정, buffer만 스윕 (버그수정 후)")
try:
    bt.STAGE1_TRIGGER_PCT = 1.5
    bt.STAGE2_LOCK_RATIO = 0.3
    for buf in [0.15, 1.0, 1.2, 1.5, 1.8, 2.0, 2.5, 3.0, 4.0]:
        bt.STAGE1_FEE_BUFFER_PCT = buf
        trades, seed = bt.run_backtest(candles_15m, breakout_mode="squeeze_avg", tp_mode="frozen",
                                        sl_first=True, use_adx_filter=True, squeeze_mult=1.5,
                                        live_staging=True, htf_trend_fn=htf_fn_1h)
        result = stats(trades)
        if result is None:
            print(f"S1buf={buf:.2f}  거래 없음")
            continue
        n, wr, pf, ret, mdd, reason_counts = result
        reason_str = ", ".join(f"{k}:{v}" for k, v in sorted(reason_counts.items()))
        print(f"S1buf={buf:5.2f}  거래{n:3d} 승률{wr:5.1f}% PF{pf:5.2f} 수익률{ret:+7.2f}% MDD{mdd:5.1f}%  [{reason_str}]")
finally:
    bt.STAGE1_TRIGGER_PCT = orig["STAGE1_TRIGGER_PCT"]
    bt.STAGE1_FEE_BUFFER_PCT = orig["STAGE1_FEE_BUFFER_PCT"]
    bt.STAGE2_LOCK_RATIO = orig["STAGE2_LOCK_RATIO"]
