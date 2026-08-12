# -*- coding: utf-8 -*-
# 2026-08-07: 사용자 요청 - BB squeeze 로직 다 제쳐두고, 순수 HMA 200/600 골든/데드크로스만으로
# 테스트. "200/600일선" = 일봉(Daily) 기준 HMA200/HMA600.
# 골든크로스(HMA200이 HMA600을 상향 돌파) -> 롱 진입, 트레일링 스탑으로 최고수익까지 보유
# 데드크로스(HMA200이 HMA600을 하향 돌파) -> 숏 진입, 트레일링 스탑으로 최고수익까지 보유
# 반대 크로스가 먼저 뜨면 즉시 포지션 스위칭(플립), 트레일링 스탑에 먼저 걸리면 플랫으로
# 전환 후 다음 크로스를 기다림.
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np
from datetime import datetime
import backtest_bb_squeeze as bt

SYMBOL = "XRPUSDT"
DAYS = 2500
INTERVAL = "D"

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
    position = None   # "long" | "short" | None
    entry = None
    entry_idx = None
    trail_ref = None

    start = None
    for i in range(len(candles)):
        if not np.isnan(hma200[i]) and not np.isnan(hma600[i]):
            start = i
            break
    if start is None:
        return trades

    def close_position(idx, price, reason):
        nonlocal position, entry, entry_idx, trail_ref
        pnl_pct = (price - entry) / entry
        if position == "short":
            pnl_pct = -pnl_pct
        nominal_seed[0] = nominal_seed[0]  # placeholder no-op (seed handled outside)
        trades.append({
            "side": position, "entry": entry, "exit": price,
            "entry_ts": candles[entry_idx]["ts"], "exit_ts": candles[idx]["ts"],
            "reason": reason, "pnl_pct": pnl_pct
        })
        position = None
        entry = None
        entry_idx = None
        trail_ref = None

    nominal_seed = [0]  # unused, kept for closure simplicity

    for t in range(start + 1, len(candles)):
        c = candles[t]
        h2, h6 = hma200[t], hma600[t]
        ph2, ph6 = hma200[t - 1], hma600[t - 1]
        if np.isnan(h2) or np.isnan(h6) or np.isnan(ph2) or np.isnan(ph6):
            continue
        golden = ph2 <= ph6 and h2 > h6
        dead = ph2 >= ph6 and h2 < h6

        # 1) 트레일링 스탑 체크 (기존 포지션)
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

        # 2) 크로스 기반 진입/플립
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


def stats(trades):
    n = len(trades)
    if n == 0:
        return None
    seed = SEED
    wins = 0
    curve = [seed]
    for tr in trades:
        nominal = seed * ENTRY_PERCENT * LEVERAGE
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
emit(f"{SYMBOL} 일봉 {len(candles)}개 ({datetime.fromtimestamp(candles[0]['ts']/1000).date()} ~ {datetime.fromtimestamp(candles[-1]['ts']/1000).date()})")

close = np.array([c["close"] for c in candles])
hma200 = hma_series(close, 200)
hma600 = hma_series(close, 600)
first_valid = next((i for i in range(len(candles)) if not np.isnan(hma600[i])), None)
emit(f"HMA600 유효 시작: {datetime.fromtimestamp(candles[first_valid]['ts']/1000).date()} (index {first_valid})")
emit("")

for trail_pct in [5, 8, 12, 18, 25]:
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
    emit(f"[trail {trail_pct}%] 거래{n:3d} 승률{wr:5.1f}% PF{pf:5.2f} 수익률{ret:+8.2f}% MDD{mdd:5.1f}% 최종시드{final_seed:8.2f}")
    emit(f"  청산사유: {reason_str}")
    for tr in trades:
        et = datetime.fromtimestamp(tr["entry_ts"]/1000).date()
        xt = datetime.fromtimestamp(tr["exit_ts"]/1000).date()
        emit(f"    {tr['side']:5s} {et}~{xt}  entry={tr['entry']:.4f} exit={tr['exit']:.4f}  pnl%={tr['pnl_pct']*100:+6.2f}  profit={tr['profit']:+8.2f}  {tr['reason']}")
    emit("")

with open("test_hma_cross_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))
