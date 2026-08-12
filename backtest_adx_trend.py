"""2026-08-12 실험: 스퀴즈+HMA200 방식과 완전히 다른, "ADX 방향(+DI/-DI)으로 추세만 타고
TP 1% / SL -1% 고정"인 제일 단순한 추세추종 테스트.

사용자 요청: "추세매매로 TP 1.0 SL -1.0 매매 한번돌려보자 SOL로만 ADX 이걸로 상승추세면 타서
1프로 먹던가 내리던가 하락추세면 1%먹던가 내리던가"

로직: 매 완성 캔들마다 ADX(14)와 +DI/-DI를 계산. ADX가 ADX_MIN 이상이면(추세 레짐) +DI>-DI면
롱, -DI>+DI면 숏 진입. 진입가 대비 +1%면 익절, -1%면 손절 (둘 다 고정 %, 다른 보호장치 없음).
같은 봉에서 SL/TP 둘 다 닿으면 보수적으로 SL 우선.

주의: run_backtest()(스퀴즈+HMA200)과는 완전히 별개의 진입/청산 로직 - 코드 공유는
fetch_klines, SEED/LEVERAGE/ENTRY_PERCENT/FEE_RATE 상수뿐. ADX 계산은 adx_at()과 동일한
Wilder's ADX 공식이지만 +DI/-DI 방향까지 같이 반환하도록 이 파일에서 별도 구현.

사용법: python backtest_adx_trend.py [SYMBOL] [DAYS] [SYMBOL2 ...]
"""
import sys

import numpy as np
import pandas as pd

import backtest_current_live as bcl

DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else bcl.DAYS

SEED = bcl.SEED
FEE_RATE = bcl.FEE_RATE
LEVERAGE = bcl.LEVERAGE
ENTRY_PERCENT = bcl.ENTRY_PERCENT
ADX_PERIOD = bcl.ADX_PERIOD

ADX_MIN = 20      # 이 이상이어야 "추세 레짐"으로 보고 진입
TP_PCT = 1.0
SL_PCT = 1.0


def adx_di_at(candles, t, period=ADX_PERIOD):
    """adx_at()과 동일 공식이지만 +DI/-DI 방향까지 같이 반환."""
    limit = period * 4 + 50
    lo = max(0, t - limit + 1)
    window = candles[lo:t + 1]
    if len(window) < period * 3:
        return None

    high = pd.Series([c["high"] for c in window])
    low = pd.Series([c["low"] for c in window])
    close = pd.Series([c["close"] for c in window])

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * pd.Series(plus_dm).ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr
    minus_di = 100 * pd.Series(minus_dm).ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    idx = len(window) - 2
    if idx < 0 or pd.isna(adx.iloc[idx]) or pd.isna(plus_di.iloc[idx]) or pd.isna(minus_di.iloc[idx]):
        return None
    return float(adx.iloc[idx]), float(plus_di.iloc[idx]), float(minus_di.iloc[idx])


def run_backtest_adx_trend(candles, adx_min=ADX_MIN, tp_pct=TP_PCT, sl_pct=SL_PCT):
    seed = SEED
    position = None
    trades = []

    min_start = ADX_PERIOD * 4 + 60

    for t in range(min_start, len(candles)):
        c = candles[t]
        ts = c["ts"]
        high, low, close = c["high"], c["low"], c["close"]

        if position:
            side = position["side"]
            entry = position["entry"]
            exit_price, reason = None, None

            if side == "long":
                if low <= position["sl_price"]:
                    exit_price, reason = position["sl_price"], "SL"
                elif high >= position["tp_price"]:
                    exit_price, reason = position["tp_price"], "TP"
            else:
                if high >= position["sl_price"]:
                    exit_price, reason = position["sl_price"], "SL"
                elif low <= position["tp_price"]:
                    exit_price, reason = position["tp_price"], "TP"

            if exit_price is not None:
                raw_pct = (exit_price - entry) / entry if side == "long" else (entry - exit_price) / entry
                notional = position["notional"]
                pnl = notional * raw_pct - notional * FEE_RATE * 2
                seed += pnl
                trades.append({
                    "entry_ts": position["entry_ts"], "exit_ts": ts, "side": side,
                    "entry": entry, "exit": exit_price, "profit": pnl,
                    "pct": raw_pct * 100, "reason": reason,
                })
                position = None
            continue

        res = adx_di_at(candles, t)
        if res is None:
            continue
        adx_val, pdi, mdi = res
        if adx_val < adx_min:
            continue
        if pdi > mdi:
            side = "long"
        elif mdi > pdi:
            side = "short"
        else:
            continue

        entry_price = close
        if side == "long":
            tp_price = entry_price * (1 + tp_pct / 100)
            sl_price = entry_price * (1 - sl_pct / 100)
        else:
            tp_price = entry_price * (1 - tp_pct / 100)
            sl_price = entry_price * (1 + sl_pct / 100)

        notional = seed * ENTRY_PERCENT * LEVERAGE
        position = {
            "side": side, "entry": entry_price, "entry_ts": ts,
            "tp_price": tp_price, "sl_price": sl_price, "notional": notional,
        }

    return trades, seed


def summarize(label, trades, final_seed):
    n = len(trades)
    print(f"\n=== {label} ===")
    if n == 0:
        print("  거래 없음")
        return
    wins = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] <= 0]
    win_rate = len(wins) / n * 100
    gross_win = sum(t["profit"] for t in wins)
    gross_loss = -sum(t["profit"] for t in losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    total_return = (final_seed - SEED) / SEED * 100
    curve = [SEED]
    s = SEED
    for t in trades:
        s += t["profit"]
        curve.append(s)
    peak = curve[0]
    mdd = 0
    for v in curve:
        peak = max(peak, v)
        dd = (peak - v) / peak * 100 if peak > 0 else 0
        mdd = max(mdd, dd)
    long_n = len([t for t in trades if t["side"] == "long"])
    short_n = len([t for t in trades if t["side"] == "short"])
    print(f"  거래 {n}건(롱{long_n}/숏{short_n}), 승률 {win_rate:.1f}%, PF {pf:.2f}, "
          f"수익률 {total_return:+.2f}%, MDD {mdd:.1f}%")
    reasons = {}
    for t in trades:
        reasons.setdefault(t["reason"], []).append(t["profit"])
    for r, ps in reasons.items():
        print(f"    {r}: {len(ps)}건, 평균손익 ${sum(ps)/len(ps):.2f}")


if __name__ == "__main__":
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["SOLUSDT"]

    for sym in coins:
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 1시간봉 데이터 수집 중...", flush=True)
        candles = bcl.fetch_klines(sym, "60", DAYS)
        print(f"캔들 {len(candles)}개 수집 완료", flush=True)

        trades, seed = run_backtest_adx_trend(candles)
        summarize(f"{sym} ADX추세추종(ADX>={ADX_MIN}, TP={TP_PCT}%, SL={SL_PCT}%)", trades, seed)

    print("\n\n=== ADX TREND TP1/SL1 TEST COMPLETE ===", flush=True)
