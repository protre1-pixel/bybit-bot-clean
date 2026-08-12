# -*- coding: utf-8 -*-
# 2026-08-07: "TP/SL 로직부터 고쳐야 하는거 아니야?" 지적에 따라, 고정 % 기반이던
# Stage1~3 트리거/버퍼를 "진입 시점 BB폭(%)" 기준 배수로 스케일링하는 vol_scaled_stages를
# backtest_bb_squeeze.py에 구현. 15분봉/1시간봉 XRP 둘 다에서 기존 고정% 방식과 비교.
import io, sys, bisect
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np
from datetime import datetime
import backtest_bb_squeeze as bt

SYMBOL = "XRPUSDT"

out_lines = []
def emit(s=""):
    print(s)
    out_lines.append(s)


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


def run_suite(label_prefix, candles_entry, htf_fn):
    for label, kwargs in [
        ("고정% 스테이지 (기존)", dict(vol_scaled_stages=False)),
        ("BB폭 비례 스테이지 (신규)", dict(vol_scaled_stages=True)),
    ]:
        trades, seed = bt.run_backtest(candles_entry, breakout_mode="squeeze_avg", tp_mode="frozen",
                                        sl_first=True, use_adx_filter=True, squeeze_mult=1.5,
                                        live_staging=True, htf_trend_fn=htf_fn, **kwargs)
        result = stats(trades)
        if result is None:
            emit(f"  [{label_prefix} | {label}] 거래 없음")
            continue
        n, wr, pf, ret, mdd, reason_counts = result
        reason_str = ", ".join(f"{k}:{v}" for k, v in sorted(reason_counts.items()))
        emit(f"  [{label_prefix} | {label}] 거래{n:3d} 승률{wr:5.1f}% PF{pf:5.2f} 수익률{ret:+7.2f}% MDD{mdd:5.1f}%")
        emit(f"      청산사유: {reason_str}")


emit("=== 15분봉 XRP (진입: squeeze_avg1.5x + ADX + 1h HTF 정배열) ===")
candles_15m = bt.fetch_klines(SYMBOL, "15", 100)
candles_1h_for15 = bt.fetch_klines(SYMBOL, "60", 160)
close_1h = np.array([c["close"] for c in candles_1h_for15])
hma200_1h = hma_series(close_1h, 200)
hma600_1h = hma_series(close_1h, 600)
htf_fn_1h = build_htf_trend_fn(candles_1h_for15, hma200_1h, hma600_1h, 3600 * 1000)
run_suite("15m", candles_15m, htf_fn_1h)
emit("")

emit("=== 1시간봉 XRP (진입: squeeze_avg1.5x + ADX, HTF필터 없음-동일TF라 의미없음) ===")
candles_1h = bt.fetch_klines(SYMBOL, "60", 100)
run_suite("1h", candles_1h, None)

with open("test_vol_scaled_stages_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))
