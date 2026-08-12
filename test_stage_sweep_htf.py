# -*- coding: utf-8 -*-
# 2026-08-07: test_htf_hma_filter.py에서 찾은 최고 진입 조합
# (squeeze_avg 1.5x + ADX 필터 + 1시간봉 HMA200/600 정배열 필터, live_staging=False 기준
#  PF1.42/+77.06%)을 진입으로 고정해두고, live_staging=True(실제 라이브 4단계 청산)의
# Stage1/2/3 파라미터를 스윕해서 개선된 진입의 효과를 청산 단계에서도 살릴 수 있는지 확인.
import io, sys, bisect
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np
from datetime import datetime
import backtest_bb_squeeze as bt

SYMBOL = "XRPUSDT"
DAYS_15M = 100
DAYS_1H = 160

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


candles_15m = bt.fetch_klines(SYMBOL, "15", DAYS_15M)
emit(f"{SYMBOL} 15분봉 {len(candles_15m)}개 ({datetime.fromtimestamp(candles_15m[0]['ts']/1000)} ~ {datetime.fromtimestamp(candles_15m[-1]['ts']/1000)})")

candles_1h = bt.fetch_klines(SYMBOL, "60", DAYS_1H)
close_1h = np.array([c["close"] for c in candles_1h])
hma200_1h = hma_series(close_1h, 200)
hma600_1h = hma_series(close_1h, 600)
htf_fn_1h = build_htf_trend_fn(candles_1h, hma200_1h, hma600_1h, 3600 * 1000)

emit("진입 고정: squeeze_avg 1.5x + ADX필터 + 1시간봉 HMA200/600 정배열 필터")
emit("Stage1/2/3 파라미터 스윕 (live_staging=True 고정)")
emit("")

# label, stage1_trigger, stage2_trigger, stage2_lock_ratio, stage3_trigger, stage3_trail_ratio, stage3_trail_min
stage_configs = [
    ("A: 현재(baseline)      S1=1.0 S2=2.0(lock50%) S3=5.0(trail30%,min3%)", 1.0, 2.0, 0.5, 5.0, 0.3, 3.0),
    ("B: lock 완화           S1=1.0 S2=2.0(lock30%) S3=5.0(trail30%,min3%)", 1.0, 2.0, 0.3, 5.0, 0.3, 3.0),
    ("C: 트리거 지연         S1=1.5 S2=3.0(lock50%) S3=6.0(trail30%,min3%)", 1.5, 3.0, 0.5, 6.0, 0.3, 3.0),
    ("D: 지연+완화 combo     S1=1.5 S2=3.0(lock30%) S3=6.0(trail30%,min3%)", 1.5, 3.0, 0.3, 6.0, 0.3, 3.0),
    ("E: 더 크게 지연+완화   S1=2.0 S2=4.0(lock30%) S3=8.0(trail30%,min3%)", 2.0, 4.0, 0.3, 8.0, 0.3, 3.0),
    ("F: 훨씬 더 여유        S1=3.0 S2=6.0(lock30%) S3=10.0(trail40%,min4%)", 3.0, 6.0, 0.3, 10.0, 0.4, 4.0),
]

orig = dict(
    STAGE1_TRIGGER_PCT=bt.STAGE1_TRIGGER_PCT,
    STAGE2_TRIGGER_PCT=bt.STAGE2_TRIGGER_PCT,
    STAGE2_LOCK_RATIO=bt.STAGE2_LOCK_RATIO,
    STAGE3_TRIGGER_PCT=bt.STAGE3_TRIGGER_PCT,
    STAGE3_TRAIL_RATIO=bt.STAGE3_TRAIL_RATIO,
    STAGE3_TRAIL_MIN_PCT=bt.STAGE3_TRAIL_MIN_PCT,
)

try:
    for label, s1, s2, lock, s3, trail_ratio, trail_min in stage_configs:
        bt.STAGE1_TRIGGER_PCT = s1
        bt.STAGE2_TRIGGER_PCT = s2
        bt.STAGE2_LOCK_RATIO = lock
        bt.STAGE3_TRIGGER_PCT = s3
        bt.STAGE3_TRAIL_RATIO = trail_ratio
        bt.STAGE3_TRAIL_MIN_PCT = trail_min

        trades, seed = bt.run_backtest(candles_15m, breakout_mode="squeeze_avg", tp_mode="frozen",
                                        sl_first=True, use_adx_filter=True, squeeze_mult=1.5,
                                        live_staging=True, htf_trend_fn=htf_fn_1h)
        result = stats(trades)
        if result is None:
            emit(f"[{label}] 거래 없음")
            continue
        n, wr, pf, ret, mdd, reason_counts = result
        reason_str = ", ".join(f"{k}:{v}" for k, v in sorted(reason_counts.items()))
        emit(f"[{label}]")
        emit(f"  거래{n:3d} 승률{wr:5.1f}% PF{pf:5.2f} 수익률{ret:+7.2f}% MDD{mdd:5.1f}%")
        emit(f"  청산사유: {reason_str}")
finally:
    bt.STAGE1_TRIGGER_PCT = orig["STAGE1_TRIGGER_PCT"]
    bt.STAGE2_TRIGGER_PCT = orig["STAGE2_TRIGGER_PCT"]
    bt.STAGE2_LOCK_RATIO = orig["STAGE2_LOCK_RATIO"]
    bt.STAGE3_TRIGGER_PCT = orig["STAGE3_TRIGGER_PCT"]
    bt.STAGE3_TRAIL_RATIO = orig["STAGE3_TRAIL_RATIO"]
    bt.STAGE3_TRAIL_MIN_PCT = orig["STAGE3_TRAIL_MIN_PCT"]

emit("")
emit("=== 참고: live_staging=False (동일 진입, 단순화 exit) ===")
trades, seed = bt.run_backtest(candles_15m, breakout_mode="squeeze_avg", tp_mode="frozen",
                                sl_first=True, use_adx_filter=True, squeeze_mult=1.5,
                                live_staging=False, htf_trend_fn=htf_fn_1h)
result = stats(trades)
if result:
    n, wr, pf, ret, mdd, reason_counts = result
    reason_str = ", ".join(f"{k}:{v}" for k, v in sorted(reason_counts.items()))
    emit(f"  거래{n:3d} 승률{wr:5.1f}% PF{pf:5.2f} 수익률{ret:+7.2f}% MDD{mdd:5.1f}%")
    emit(f"  청산사유: {reason_str}")

with open("test_stage_sweep_htf_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))
