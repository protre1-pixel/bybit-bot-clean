# -*- coding: utf-8 -*-
# 2026-08-07: test_hma_simple.py에 ADX/DI 추세강도 필터를 얹은 버전.
# 크로스가 떠도 ADX가 임계값 미만이면(=횡보 구간) 그 크로스는 무시하고 기존 상태 유지.
# ADX가 임계값 이상이고 +DI/-DI가 방향까지 확인해줄 때만 크로스를 "진짜 신호"로 인정.
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np
from datetime import datetime
import backtest_bb_squeeze as bt

SYMBOL = "XRPUSDT"
DAYS = 180
INTERVAL = "15"
FEE_PCT = 0.055 * 2 / 100

out_lines = []
def emit(s=""):
    print(s)
    out_lines.append(s)


def wma(values, period):
    n = len(values)
    out = np.full(n, np.nan)
    weights = np.arange(1, period + 1)
    wsum = weights.sum()
    for i in range(period - 1, n):
        out[i] = np.sum(weights * values[i - period + 1:i + 1]) / wsum
    return out


def hma(values, period):
    half = period // 2
    sq = int(np.sqrt(period))
    diff = 2 * wma(values, half) - wma(values, period)
    return wma(diff, sq)


def run(candles, h200, h600, trail_pct, adx_threshold):
    trades = []
    pos = None
    entry = None
    entry_i = None
    peak = None
    filtered_out = 0

    start = next(i for i in range(len(candles)) if not np.isnan(h600[i]))

    def close(i, price, reason):
        nonlocal pos, entry, entry_i, peak
        chg = (price - entry) / entry
        if pos == "short":
            chg = -chg
        trades.append(dict(side=pos, entry=entry, exit=price,
                            entry_i=entry_i, exit_i=i, reason=reason, chg=chg))
        pos = entry = entry_i = peak = None

    for t in range(start + 1, len(candles)):
        c = candles[t]
        h2, h6, ph2, ph6 = h200[t], h600[t], h200[t - 1], h600[t - 1]
        if np.isnan(h2) or np.isnan(h6) or np.isnan(ph2) or np.isnan(ph6):
            continue
        golden = ph2 <= ph6 and h2 > h6
        dead = ph2 >= ph6 and h2 < h6

        if pos == "long":
            peak = max(peak, c["high"])
            if c["low"] <= peak * (1 - trail_pct / 100):
                close(t, peak * (1 - trail_pct / 100), "trail")
        elif pos == "short":
            peak = min(peak, c["low"])
            if c["high"] >= peak * (1 + trail_pct / 100):
                close(t, peak * (1 + trail_pct / 100), "trail")

        if golden or dead:
            adx_info = bt.adx_at(candles, t)
            ok = False
            if adx_info is not None and adx_info["adx"] >= adx_threshold:
                if golden and adx_info["plus_di"] > adx_info["minus_di"]:
                    ok = True
                elif dead and adx_info["minus_di"] > adx_info["plus_di"]:
                    ok = True
            if not ok:
                filtered_out += 1
            else:
                if golden:
                    if pos == "short":
                        close(t, c["close"], "flip")
                    if pos is None:
                        pos, entry, entry_i, peak = "long", c["close"], t, c["close"]
                elif dead:
                    if pos == "long":
                        close(t, c["close"], "flip")
                    if pos is None:
                        pos, entry, entry_i, peak = "short", c["close"], t, c["close"]

    return trades, filtered_out


candles = bt.fetch_klines(SYMBOL, INTERVAL, DAYS)
close = np.array([c["close"] for c in candles])
h200 = hma(close, 200)
h600 = hma(close, 600)
emit(f"{SYMBOL} {INTERVAL}분봉 {len(candles)}개 ({datetime.fromtimestamp(candles[0]['ts']/1000)} ~ {datetime.fromtimestamp(candles[-1]['ts']/1000)})")
emit("")

for trail_pct in [3, 5]:
    for adx_th in [15, 20, 25]:
        trades, filtered_out = run(candles, h200, h600, trail_pct, adx_th)
        equity = 1.0
        curve = [1.0]
        wins = 0
        for tr in trades:
            equity *= (1 + tr["chg"] - FEE_PCT)
            curve.append(equity)
            if tr["chg"] > FEE_PCT:
                wins += 1
        n = len(trades)
        wr = wins / n * 100 if n else 0
        ret = (equity - 1) * 100
        peak_eq = curve[0]
        mdd = 0
        for v in curve:
            peak_eq = max(peak_eq, v)
            mdd = max(mdd, (peak_eq - v) / peak_eq * 100)
        emit(f"[trail {trail_pct}%, ADX>={adx_th}] 거래{n:3d}건(필터탈락{filtered_out}) 승률{wr:5.1f}% 누적수익률{ret:+8.2f}% MDD{mdd:5.1f}%")

emit("")
emit("=== 참고: 필터 없는 baseline ===")
for trail_pct in [3, 5]:
    trades = []
    pos = None; entry = None; entry_i = None; peak = None
    start = next(i for i in range(len(candles)) if not np.isnan(h600[i]))
    for t in range(start + 1, len(candles)):
        c = candles[t]
        h2, h6, ph2, ph6 = h200[t], h600[t], h200[t - 1], h600[t - 1]
        if np.isnan(h2) or np.isnan(h6) or np.isnan(ph2) or np.isnan(ph6):
            continue
        golden = ph2 <= ph6 and h2 > h6
        dead = ph2 >= ph6 and h2 < h6
        if pos == "long":
            peak = max(peak, c["high"])
            if c["low"] <= peak * (1 - trail_pct / 100):
                chg = (peak*(1-trail_pct/100) - entry)/entry
                trades.append(dict(chg=chg)); pos=entry=entry_i=peak=None
        elif pos == "short":
            peak = min(peak, c["low"])
            if c["high"] >= peak * (1 + trail_pct / 100):
                chg = -( (peak*(1+trail_pct/100) - entry)/entry )
                trades.append(dict(chg=chg)); pos=entry=entry_i=peak=None
        if golden:
            if pos == "short":
                chg = -((c["close"]-entry)/entry); trades.append(dict(chg=chg)); pos=None
            if pos is None:
                pos, entry, entry_i, peak = "long", c["close"], t, c["close"]
        elif dead:
            if pos == "long":
                chg = (c["close"]-entry)/entry; trades.append(dict(chg=chg)); pos=None
            if pos is None:
                pos, entry, entry_i, peak = "short", c["close"], t, c["close"]
    equity = 1.0
    wins = 0
    for tr in trades:
        equity *= (1 + tr["chg"] - FEE_PCT)
        if tr["chg"] > FEE_PCT:
            wins += 1
    n = len(trades)
    ret = (equity-1)*100
    wr = wins/n*100 if n else 0
    emit(f"[trail {trail_pct}%, 필터없음] 거래{n:3d}건 승률{wr:5.1f}% 누적수익률{ret:+8.2f}%")

with open("test_hma_adx_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))
