# -*- coding: utf-8 -*-
# 2026-08-07: 완전히 새로 짠 최소 버전. 레버리지/수수료/포지션비중 같은 머니매니지먼트
# 다 빼고, 순수 가격 등락률만으로 계산 (왜곡 요인 제거해서 신호 자체의 edge만 본다).
#
# 규칙:
#  - 골든크로스(HMA200이 HMA600 상향 돌파): 매수 진입 (숏 보유중이면 먼저 청산)
#  - 데드크로스(HMA200이 HMA600 하향 돌파): 매도 진입 (롱 보유중이면 먼저 청산)
#  - 보유 중에는 "정배열이 깨지기 전까지" 계속 들고가되, 트레일링 스탑으로 보호
#    (peak 대비 trail_pct% 반납하면 즉시 청산, 그 전까지는 계속 보유)
#  - 트레일링에 안 걸리면 반대 크로스가 뜰 때까지 계속 보유 (기간 제한 없음)
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np
from datetime import datetime
import backtest_bb_squeeze as bt

SYMBOL = "XRPUSDT"
DAYS = 180
INTERVAL = "15"
FEE_PCT = 0.055 * 2 / 100  # 왕복 수수료 (0.055% x 2)

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


def run(candles, h200, h600, trail_pct):
    trades = []
    pos = None       # "long" | "short" | None
    entry = None
    entry_i = None
    peak = None       # long: 최고가, short: 최저가

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

    return trades


candles = bt.fetch_klines(SYMBOL, INTERVAL, DAYS)
close = np.array([c["close"] for c in candles])
h200 = hma(close, 200)
h600 = hma(close, 600)
emit(f"{SYMBOL} {INTERVAL}분봉 {len(candles)}개 ({datetime.fromtimestamp(candles[0]['ts']/1000)} ~ {datetime.fromtimestamp(candles[-1]['ts']/1000)})")
emit("")

for trail_pct in [2, 3, 5]:
    trades = run(candles, h200, h600, trail_pct)
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
    emit(f"===== trail {trail_pct}% : 거래{n}건, 승률{wr:.1f}%, 누적수익률{ret:+.2f}%, MDD{mdd:.1f}% =====")
    for tr in trades:
        et = datetime.fromtimestamp(candles[tr["entry_i"]]["ts"]/1000)
        xt = datetime.fromtimestamp(candles[tr["exit_i"]]["ts"]/1000)
        emit(f"  {tr['side']:5s} {et}~{xt}  entry={tr['entry']:.4f} exit={tr['exit']:.4f}  "
             f"수익률={tr['chg']*100:+6.2f}%  청산={tr['reason']}")
    emit("")

with open("test_hma_simple_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))
