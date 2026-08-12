# -*- coding: utf-8 -*-
# 2026-08-07: 사용자 제안 - "1단계(breakeven, 살짝 벌면 바로 본전 잠그기)가 오히려
# 노이즈에 조기청산당하는 원인 아니냐"는 가설. 1단계를 통째로 스킵하고 0→2→3단계로만
# 진행하는 skip_stage1을 backtest_bb_squeeze.py에 구현했으니, XRP/BTC/ETH/SOL/DOGE
# 5개 코인 동시에 스윕해서 실제로 개선되는지 확인 (지난번 vol_scaled_stages 과최적화
# 반복 안 하려고 처음부터 멀티코인). 진입조건은 지금까지 제일 나았던 squeeze_avg 1.5x
# + ADX + 1h HTF HMA200/600 정배열 고정, 15분봉 기준. 고정%/BB폭비례 스테이징 둘 다에
# skip_stage1 얹어서 4가지 조합 비교.
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

configs = [
    ("A: 고정% 4단계 (기존 베이스라인)", dict(vol_scaled_stages=False, skip_stage1=False)),
    ("B: 고정% + 1단계 스킵 (0→2→3)", dict(vol_scaled_stages=False, skip_stage1=True)),
    ("C: BB폭비례 4단계", dict(vol_scaled_stages=True, skip_stage1=False)),
    ("D: BB폭비례 + 1단계 스킵 (0→2→3)", dict(vol_scaled_stages=True, skip_stage1=True)),
]

for label, kwargs in configs:
    emit(f"=== {label} ===")
    rets = []
    pfs = []
    positive_count = 0
    for symbol in SYMBOLS:
        candles_15m, htf_fn = coin_data[symbol]
        trades, seed = bt.run_backtest(candles_15m, breakout_mode="squeeze_avg", tp_mode="frozen",
                                        sl_first=True, use_adx_filter=True, squeeze_mult=1.5,
                                        live_staging=True, htf_trend_fn=htf_fn, **kwargs)
        result = stats(trades)
        if result is None:
            emit(f"  {symbol:10s} 거래없음")
            continue
        n, wr, pf, ret, mdd, reason_counts = result
        reason_str = ", ".join(f"{k}:{v}" for k, v in sorted(reason_counts.items()))
        rets.append(ret)
        pfs.append(pf if pf != float("inf") else 5.0)
        if ret > 0:
            positive_count += 1
        emit(f"  {symbol:10s} 거래{n:3d} 승률{wr:5.1f}% PF{pf:5.2f} 수익률{ret:+7.2f}% MDD{mdd:5.1f}%  [{reason_str}]")

    avg_ret = sum(rets) / len(rets) if rets else 0
    avg_pf = sum(pfs) / len(pfs) if pfs else 0
    emit(f"  --> 평균수익률 {avg_ret:+7.2f}%  평균PF {avg_pf:5.2f}  플러스코인 {positive_count}/{len(rets)}")
    emit("")

with open("test_skip_stage1_multicoin_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))
