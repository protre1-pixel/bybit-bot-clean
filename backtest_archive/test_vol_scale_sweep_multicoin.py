# -*- coding: utf-8 -*-
# 2026-08-07: vol_scaled_stages(BB폭 비례 Stage1~3) 배수를 스윕. 지난번 실수(XRP 하나로만
# 최적화해서 과최적화됨)를 반복 안 하려고, 처음부터 여러 코인(XRP/BTC/ETH/SOL/DOGE) 동시에
# 놓고 "전체적으로 골고루 나아지는" 배수를 찾는다. 진입조건은 지금까지 제일 나았던
# squeeze_avg 1.5x + ADX + 1h HTF HMA200/600 정배열 그대로 고정, 15분봉 기준.
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
    return n, wr, pf, ret, mdd


# 코인별 캔들 미리 로드 (스윕 중 반복 호출 안 하려고)
emit("데이터 로딩 중...")
coin_data = {}
for symbol in SYMBOLS:
    candles_15m = bt.fetch_klines(symbol, "15", DAYS_15M)
    candles_1h = bt.fetch_klines(symbol, "60", DAYS_1H)
    close_1h = np.array([c["close"] for c in candles_1h])
    hma200_1h = hma_series(close_1h, 200)
    hma600_1h = hma_series(close_1h, 600)
    htf_fn = build_htf_trend_fn(candles_1h, hma200_1h, hma600_1h, 3600 * 1000)
    coin_data[symbol] = (candles_15m, htf_fn)
emit("로딩 완료")
emit("")

# baseline 배수 * scale
base = dict(s1_trig=0.5, s1_buf=0.1, s2_trig=1.0, s3_trig=2.5, s3_min=0.5)
scales = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0]

orig = dict(
    VOL_S1_TRIGGER_MULT=bt.VOL_S1_TRIGGER_MULT,
    VOL_S1_BUFFER_MULT=bt.VOL_S1_BUFFER_MULT,
    VOL_S2_TRIGGER_MULT=bt.VOL_S2_TRIGGER_MULT,
    VOL_S3_TRIGGER_MULT=bt.VOL_S3_TRIGGER_MULT,
    VOL_S3_TRAIL_MIN_MULT=bt.VOL_S3_TRAIL_MIN_MULT,
)

try:
    for scale in scales:
        bt.VOL_S1_TRIGGER_MULT = base["s1_trig"] * scale
        bt.VOL_S1_BUFFER_MULT = base["s1_buf"] * scale
        bt.VOL_S2_TRIGGER_MULT = base["s2_trig"] * scale
        bt.VOL_S3_TRIGGER_MULT = base["s3_trig"] * scale
        bt.VOL_S3_TRAIL_MIN_MULT = base["s3_min"] * scale

        emit(f"=== scale={scale}x  (S1trig={bt.VOL_S1_TRIGGER_MULT:.2f} buf={bt.VOL_S1_BUFFER_MULT:.2f} "
             f"S2trig={bt.VOL_S2_TRIGGER_MULT:.2f} S3trig={bt.VOL_S3_TRIGGER_MULT:.2f} S3min={bt.VOL_S3_TRAIL_MIN_MULT:.2f}) ===")

        rets = []
        pfs = []
        positive_count = 0
        for symbol in SYMBOLS:
            candles_15m, htf_fn = coin_data[symbol]
            trades, seed = bt.run_backtest(candles_15m, breakout_mode="squeeze_avg", tp_mode="frozen",
                                            sl_first=True, use_adx_filter=True, squeeze_mult=1.5,
                                            live_staging=True, htf_trend_fn=htf_fn, vol_scaled_stages=True)
            result = stats(trades)
            if result is None:
                emit(f"  {symbol:10s} 거래없음")
                continue
            n, wr, pf, ret, mdd = result
            rets.append(ret)
            pfs.append(pf if pf != float("inf") else 5.0)
            if ret > 0:
                positive_count += 1
            emit(f"  {symbol:10s} 거래{n:3d} 승률{wr:5.1f}% PF{pf:5.2f} 수익률{ret:+7.2f}% MDD{mdd:5.1f}%")

        avg_ret = sum(rets) / len(rets) if rets else 0
        avg_pf = sum(pfs) / len(pfs) if pfs else 0
        emit(f"  --> 평균수익률 {avg_ret:+7.2f}%  평균PF {avg_pf:5.2f}  플러스코인 {positive_count}/{len(rets)}")
        emit("")
finally:
    bt.VOL_S1_TRIGGER_MULT = orig["VOL_S1_TRIGGER_MULT"]
    bt.VOL_S1_BUFFER_MULT = orig["VOL_S1_BUFFER_MULT"]
    bt.VOL_S2_TRIGGER_MULT = orig["VOL_S2_TRIGGER_MULT"]
    bt.VOL_S3_TRIGGER_MULT = orig["VOL_S3_TRIGGER_MULT"]
    bt.VOL_S3_TRAIL_MIN_MULT = orig["VOL_S3_TRAIL_MIN_MULT"]

with open("test_vol_scale_sweep_multicoin_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))
