# -*- coding: utf-8 -*-
# 2026-08-07: 사용자 지적 - "지금 진입시점 타이밍은 진짜 딱 내가 원하는거야" → 청산(TP/SL)
# 튜닝은 잠시 멈추고 진입 타이밍부터 다시 보자는 요청. 스퀴즈 구간 동안 폭들의 "평균"으로
# 발동 문턱을 잡는 squeeze_avg(v3) 대신, 스퀴즈 진입 이후 계속 갱신되는 "최저점"*1.5를
# 문턱으로 잡는 squeeze(v2, 이미 구현되어 있었음 - 예전엔 필터 없이 테스트해서 노이즈에
# 취약하다고 봤었는데, 지금 확정된 ADX+1h HTF 필터를 얹은 채로는 아직 비교 안 해봄)로
# 되돌려서 XRP/BTC/ETH/SOL/DOGE 5개 코인 동시에 비교. 청산은 일단 기존 고정% 4단계
# 베이스라인 그대로 둬서(entry_sizing="bb", vol_scaled_stages=False, skip_stage1=False)
# "진입 타이밍 변경 효과"만 격리해서 본다. squeeze_mult(1.5 고정 vs 살짝 스윕)도 같이 확인.
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
    ("A: squeeze_avg (평균기준, 기존)", dict(breakout_mode="squeeze_avg", squeeze_mult=1.5)),
    ("B: squeeze (최저점기준) x1.5", dict(breakout_mode="squeeze", squeeze_mult=1.5)),
    ("C: squeeze (최저점기준) x1.3", dict(breakout_mode="squeeze", squeeze_mult=1.3)),
    ("D: squeeze (최저점기준) x2.0", dict(breakout_mode="squeeze", squeeze_mult=2.0)),
]

for label, kwargs in configs:
    emit(f"=== {label} ===")
    rets = []
    pfs = []
    positive_count = 0
    for symbol in SYMBOLS:
        candles_15m, htf_fn = coin_data[symbol]
        trades, seed = bt.run_backtest(candles_15m, tp_mode="frozen",
                                        sl_first=True, use_adx_filter=True,
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

with open("test_squeeze_min_multicoin_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))
