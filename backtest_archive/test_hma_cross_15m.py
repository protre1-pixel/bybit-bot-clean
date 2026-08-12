# -*- coding: utf-8 -*-
# 2026-08-07: test_hma_cross.py(일봉 버전)와 동일한 로직, 타임프레임만 15분봉/6개월로 변경.
# HMA200/HMA600 골든/데드크로스 + 트레일링 전용 (BB squeeze 로직 배제).
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np
from datetime import datetime
import backtest_bb_squeeze as bt

SYMBOL = "XRPUSDT"
DAYS = 180          # 6개월
INTERVAL = "15"      # 15분봉

SEED = bt.SEED
ENTRY_PERCENT = bt.ENTRY_PERCENT
LEVERAGE = bt.LEVERAGE
FEE_RATE = bt.FEE_RATE

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


def simulate(candles, hma200, hma600, trail_pct):
    trades = []
    position = None
    entry = None
    entry_idx = None
    trail_ref = None

    start = next((i for i in range(len(candles)) if not np.isnan(hma600[i])), None)
    if start is None:
        return trades

    def close_position(idx, price, reason):
        nonlocal position, entry, entry_idx, trail_ref
        pnl_pct = (price - entry) / entry
        if position == "short":
            pnl_pct = -pnl_pct
        trades.append({
            "side": position, "entry": entry, "exit": price,
            "entry_ts": candles[entry_idx]["ts"], "exit_ts": candles[idx]["ts"],
            "reason": reason, "pnl_pct": pnl_pct
        })
        position = None
        entry = None
        entry_idx = None
        trail_ref = None

    for t in range(start + 1, len(candles)):
        c = candles[t]
        h2, h6 = hma200[t], hma600[t]
        ph2, ph6 = hma200[t - 1], hma600[t - 1]
        if np.isnan(h2) or np.isnan(h6) or np.isnan(ph2) or np.isnan(ph6):
            continue
        golden = ph2 <= ph6 and h2 > h6
        dead = ph2 >= ph6 and h2 < h6

        if position == "long":
            if c["high"] > trail_ref:
                trail_ref = c["high"]
            stop = trail_ref * (1 - trail_pct / 100)
            if c["low"] <= stop:
                close_position(t, stop, "Trailing Stop")
        elif position == "short":
            if c["low"] < trail_ref:
                trail_ref = c["low"]
            stop = trail_ref * (1 + trail_pct / 100)
            if c["high"] >= stop:
                close_position(t, stop, "Trailing Stop")

        if golden:
            if position == "short":
                close_position(t, c["close"], "Dead->Golden Flip")
            if position is None:
                position, entry, entry_idx, trail_ref = "long", c["close"], t, c["close"]
        elif dead:
            if position == "long":
                close_position(t, c["close"], "Golden->Dead Flip")
            if position is None:
                position, entry, entry_idx, trail_ref = "short", c["close"], t, c["close"]

    return trades


def stats(trades, leverage=LEVERAGE):
    n = len(trades)
    if n == 0:
        return None
    seed = SEED
    wins = 0
    curve = [seed]
    for tr in trades:
        nominal = seed * ENTRY_PERCENT * leverage
        gross = nominal * tr["pnl_pct"]
        fees = nominal * FEE_RATE * 2
        net = gross - fees
        seed += net
        tr["profit"] = net
        if net > 0:
            wins += 1
        curve.append(seed)
    wr = wins / n * 100
    gw = sum(tr["profit"] for tr in trades if tr["profit"] > 0)
    gl = -sum(tr["profit"] for tr in trades if tr["profit"] <= 0)
    pf = gw / gl if gl > 0 else float("inf")
    ret = (seed - SEED) / SEED * 100
    peak = curve[0]
    mdd = 0
    for v in curve:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak * 100)
    return n, wr, pf, ret, mdd, seed


candles = bt.fetch_klines(SYMBOL, INTERVAL, DAYS)
emit(f"{SYMBOL} {INTERVAL}분봉 {len(candles)}개 ({datetime.fromtimestamp(candles[0]['ts']/1000)} ~ {datetime.fromtimestamp(candles[-1]['ts']/1000)})")

close = np.array([c["close"] for c in candles])
hma200 = hma_series(close, 200)
hma600 = hma_series(close, 600)
first_valid = next((i for i in range(len(candles)) if not np.isnan(hma600[i])), None)
emit(f"HMA600 유효 시작: {datetime.fromtimestamp(candles[first_valid]['ts']/1000)} (index {first_valid})")
emit("")

for trail_pct in [1, 2, 3, 5, 8]:
    trades = simulate(candles, hma200, hma600, trail_pct)
    result = stats(trades)
    if result is None:
        emit(f"[trail {trail_pct}%] 거래 없음")
        continue
    n, wr, pf, ret, mdd, final_seed = result
    reason_counts = {}
    for tr in trades:
        reason_counts[tr["reason"]] = reason_counts.get(tr["reason"], 0) + 1
    reason_str = ", ".join(f"{k}:{v}" for k, v in sorted(reason_counts.items()))
    emit(f"[trail {trail_pct}%] 거래{n:4d} 승률{wr:5.1f}% PF{pf:5.2f} 수익률{ret:+9.2f}% MDD{mdd:6.1f}% 최종시드{final_seed:10.2f}")
    emit(f"  청산사유: {reason_str}")

emit("")
emit("=== 참고: 레버리지 1x(현물 기준)로 신호 자체의 순수 edge 확인 ===")
for trail_pct in [1, 2, 3, 5, 8]:
    trades = simulate(candles, hma200, hma600, trail_pct)
    result = stats(trades, leverage=1)
    if result is None:
        continue
    n, wr, pf, ret, mdd, final_seed = result
    emit(f"[trail {trail_pct}%, 1x] 거래{n:4d} 승률{wr:5.1f}% PF{pf:5.2f} 수익률{ret:+9.2f}% MDD{mdd:6.1f}%")

with open("test_hma_cross_15m_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))
