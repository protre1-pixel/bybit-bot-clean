# -*- coding: utf-8 -*-
# 2026-08-07: 사용자 제안 - 예전에 ATR 기반으로 하다가 BB로 넘어왔는데 ATR도 나쁘지
# 않았다고 함. 지금 초기 SL폭(entry_bb_width)이 "스퀴즈 브레이크아웃 순간"의 BB폭이라
# 정의상 좁은 상태라 초반 Stop Loss 비율이 너무 높은 문제(BTC 70% 등)의 원인일 수 있음.
# entry_sizing="atr"을 backtest_bb_squeeze.py에 구현했으니, 초기 TP/SL 폭 산정 기준을
# BB폭 대신 ATR*배수로 바꿔서 XRP/BTC/ETH/SOL/DOGE 5개 코인 동시에 비교.
# 진입조건은 지금까지 제일 나았던 squeeze_avg 1.5x + ADX + 1h HTF HMA200/600 정배열 고정,
# 15분봉, 청산은 고정% 4단계 기본(live_staging=True) 그대로 두고 entry_sizing만 바꿔서
# "초기 SL폭 자체"의 효과만 격리해서 본다. ATR 배수는 1.0/1.5/2.0/2.5 스윕.
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
    ("A: BB폭 기준 (기존 베이스라인)", dict(entry_sizing="bb")),
    ("B: ATR*1.0", dict(entry_sizing="atr", atr_mult=1.0)),
    ("C: ATR*1.5", dict(entry_sizing="atr", atr_mult=1.5)),
    ("D: ATR*2.0", dict(entry_sizing="atr", atr_mult=2.0)),
    ("E: ATR*2.5", dict(entry_sizing="atr", atr_mult=2.5)),
]

for label, kwargs in configs:
    emit(f"=== {label} ===")
    rets = []
    pfs = []
    positive_count = 0
    total_sl = 0
    total_trades = 0
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
        total_sl += reason_counts.get("Stop Loss", 0)
        total_trades += n
        emit(f"  {symbol:10s} 거래{n:3d} 승률{wr:5.1f}% PF{pf:5.2f} 수익률{ret:+7.2f}% MDD{mdd:5.1f}%  [{reason_str}]")

    avg_ret = sum(rets) / len(rets) if rets else 0
    avg_pf = sum(pfs) / len(pfs) if pfs else 0
    sl_ratio = total_sl / total_trades * 100 if total_trades else 0
    emit(f"  --> 평균수익률 {avg_ret:+7.2f}%  평균PF {avg_pf:5.2f}  플러스코인 {positive_count}/{len(rets)}  초기SL비율 {sl_ratio:4.1f}%")
    emit("")

with open("test_atr_sizing_multicoin_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))
