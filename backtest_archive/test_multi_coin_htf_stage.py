# -*- coding: utf-8 -*-
# 2026-08-07: XRP에서 찾은 조합(진입: squeeze_avg 1.5x + ADX + 1h HMA200/600 정배열,
# 청산: live_staging=True, STAGE1_TRIGGER=1.5/buf=2.0, STAGE2_LOCK_RATIO=0.3,
# STAGE2_TRIGGER/STAGE3는 기본값)이 XRP 데이터에만 과최적화된 건 아닌지 확인하기 위해
# 다른 코인들(BTC/ETH/SOL/DOGE)에도 똑같은 조건 그대로 적용해서 out-of-symbol 검증.
import io, sys, bisect
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np
from datetime import datetime
import backtest_bb_squeeze as bt

SYMBOLS = ["XRPUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"]
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


orig = dict(
    STAGE1_TRIGGER_PCT=bt.STAGE1_TRIGGER_PCT,
    STAGE1_FEE_BUFFER_PCT=bt.STAGE1_FEE_BUFFER_PCT,
    STAGE2_LOCK_RATIO=bt.STAGE2_LOCK_RATIO,
)

emit("동일 조건(진입: squeeze_avg1.5x+ADX+1h HMA200/600 정배열, 청산: live_staging=True")
emit("  STAGE1_TRIGGER=1.5/buf=2.0, STAGE2_LOCK_RATIO=0.3, 나머지 기본값)을 여러 코인에 적용")
emit("")

try:
    bt.STAGE1_TRIGGER_PCT = 1.5
    bt.STAGE1_FEE_BUFFER_PCT = 2.0
    bt.STAGE2_LOCK_RATIO = 0.3

    for symbol in SYMBOLS:
        try:
            candles_15m = bt.fetch_klines(symbol, "15", DAYS_15M)
            candles_1h = bt.fetch_klines(symbol, "60", DAYS_1H)
        except Exception as e:
            emit(f"[{symbol}] 데이터 조회 실패: {e}")
            continue

        close_1h = np.array([c["close"] for c in candles_1h])
        hma200_1h = hma_series(close_1h, 200)
        hma600_1h = hma_series(close_1h, 600)
        htf_fn_1h = build_htf_trend_fn(candles_1h, hma200_1h, hma600_1h, 3600 * 1000)

        trades, seed = bt.run_backtest(candles_15m, breakout_mode="squeeze_avg", tp_mode="frozen",
                                        sl_first=True, use_adx_filter=True, squeeze_mult=1.5,
                                        live_staging=True, htf_trend_fn=htf_fn_1h)
        result = stats(trades)
        if result is None:
            emit(f"[{symbol}] 거래 없음 (15분봉 {len(candles_15m)}개, "
                 f"{datetime.fromtimestamp(candles_15m[0]['ts']/1000)}~{datetime.fromtimestamp(candles_15m[-1]['ts']/1000)})")
            continue
        n, wr, pf, ret, mdd, reason_counts = result
        reason_str = ", ".join(f"{k}:{v}" for k, v in sorted(reason_counts.items()))
        emit(f"[{symbol}]  ({datetime.fromtimestamp(candles_15m[0]['ts']/1000).strftime('%Y-%m-%d')}~"
             f"{datetime.fromtimestamp(candles_15m[-1]['ts']/1000).strftime('%Y-%m-%d')})")
        emit(f"  거래{n:3d} 승률{wr:5.1f}% PF{pf:5.2f} 수익률{ret:+7.2f}% MDD{mdd:5.1f}%")
        emit(f"  청산사유: {reason_str}")
        emit("")
finally:
    bt.STAGE1_TRIGGER_PCT = orig["STAGE1_TRIGGER_PCT"]
    bt.STAGE1_FEE_BUFFER_PCT = orig["STAGE1_FEE_BUFFER_PCT"]
    bt.STAGE2_LOCK_RATIO = orig["STAGE2_LOCK_RATIO"]

with open("test_multi_coin_htf_stage_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))
