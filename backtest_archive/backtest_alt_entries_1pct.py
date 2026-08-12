"""2026-08-12 실험: "1%를 자주, 안정적으로" - RSI 말고 다른 진입 신호 계열 탐색.

배경: backtest_meanrev_1pct.py에서 RSI 과매도/과매수 기반 진입은 15분봉/1시간봉 둘 다
필터를 아무리 걸어도 대실패(-9%~-100%)였음. 구조적 원인: SL이 TP보다 커서 손익분기
승률이 높은데(~60%대), 필터로 승률을 올리면 거래수가 너무 줄어서 우위가 못 쌓임.

이번엔 RSI 계열이 아닌, 성격이 다른 3가지 진입 신호를 테스트:
  1) EMA 눌림목 되돌림 (pullback): 짧은 추세추종. EMA9/21 정배열(추세) 중 가격이 EMA9까지
     눌렸다가 다시 돌파하면 진입. SL을 ATR 기반으로 타이트하게 잡아서 RSI 버전의 "SL>TP라
     손익분기가 불리한" 구조적 문제를 완화해봄.
  2) 스토캐스틱(%K/%D) 과매수/과매도 크로스: RSI와 다른 민감도의 오실레이터.
  3) 돈치안채널(Donchian) 브레이크아웃: N봉 신고가/신저가 돌파 - 모멘텀 추종형.
     (참고: 다른 프로젝트에서 Donchian+EMA200+ADX 일봉 전략으로 검증된 계열의 변형)

전부 15분봉 고정(사용자 지시), 365일, XRP/ETH/BTC/SOL만.

사용법: python backtest_alt_entries_1pct.py [SYMBOL] [DAYS] [SYMBOL2 ...]
"""
import os
import sys

import numpy as np
import pandas as pd

import backtest_current_live as bcl

DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else bcl.DAYS
INTERVAL = os.environ.get("ALT_INTERVAL", "15")  # 2026-08-12: 1시간봉 비교용으로 env로 전환 가능

SEED = bcl.SEED
LEVERAGE = bcl.LEVERAGE
ENTRY_PERCENT = bcl.ENTRY_PERCENT
FEE_RATE = bcl.FEE_RATE

ATR_PERIOD = 14
EMA_FAST, EMA_SLOW = 9, 21
STOCH_PERIOD, STOCH_SMOOTH = 14, 3
DONCHIAN_PERIOD = 20


def compute_indicators(candles):
    close = pd.Series([c["close"] for c in candles])
    high = pd.Series([c["high"] for c in candles])
    low = pd.Series([c["low"] for c in candles])

    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / ATR_PERIOD, adjust=False, min_periods=ATR_PERIOD).mean()

    ema_fast = close.ewm(span=EMA_FAST, adjust=False).mean()
    ema_slow = close.ewm(span=EMA_SLOW, adjust=False).mean()

    lowest_low = low.rolling(STOCH_PERIOD).min()
    highest_high = high.rolling(STOCH_PERIOD).max()
    pct_k = 100 * (close - lowest_low) / (highest_high - lowest_low)
    pct_d = pct_k.rolling(STOCH_SMOOTH).mean()

    # 돈치안: 당일(현재봉) 제외 - shift(1) 후 rolling으로 lookahead 방지
    donch_upper = high.shift(1).rolling(DONCHIAN_PERIOD).max()
    donch_lower = low.shift(1).rolling(DONCHIAN_PERIOD).min()

    return {
        "close": close.values, "high": high.values, "low": low.values,
        "atr": atr.values, "ema_fast": ema_fast.values, "ema_slow": ema_slow.values,
        "pct_k": pct_k.values, "pct_d": pct_d.values,
        "donch_upper": donch_upper.values, "donch_lower": donch_lower.values,
    }


def entry_ema_pullback(ind, i):
    ef, es = ind["ema_fast"], ind["ema_slow"]
    close = ind["close"]
    if np.isnan(ef[i]) or np.isnan(es[i]) or np.isnan(ef[i - 1]):
        return None
    trend_up = ef[i] > es[i]
    trend_down = ef[i] < es[i]
    if trend_up and close[i] > ef[i] and close[i - 1] <= ef[i - 1]:
        return "long"
    if trend_down and close[i] < ef[i] and close[i - 1] >= ef[i - 1]:
        return "short"
    return None


def entry_stochastic(ind, i, os=20, ob=80):
    k, d = ind["pct_k"], ind["pct_d"]
    if np.isnan(k[i]) or np.isnan(d[i]) or np.isnan(k[i - 1]) or np.isnan(d[i - 1]):
        return None
    if d[i] < os and k[i - 1] <= d[i - 1] and k[i] > d[i]:
        return "long"
    if d[i] > ob and k[i - 1] >= d[i - 1] and k[i] < d[i]:
        return "short"
    return None


def entry_donchian(ind, i):
    close = ind["close"]
    du, dl = ind["donch_upper"], ind["donch_lower"]
    if np.isnan(du[i]) or np.isnan(dl[i]):
        return None
    if close[i] > du[i]:
        return "long"
    if close[i] < dl[i]:
        return "short"
    return None


ENTRY_FUNCS = {
    "EMA눌림목": entry_ema_pullback,
    "스토캐스틱": entry_stochastic,
    "돈치안돌파": entry_donchian,
}


def run_backtest(candles, ind, entry_fn, tp_pct=1.0, sl_mode="atr", sl_atr_mult=1.5, sl_pct=1.5,
                  max_hold_h=24, cooldown_h=1.0):
    n = len(candles)
    close, high, low, atr = ind["close"], ind["high"], ind["low"], ind["atr"]

    warmup = max(DONCHIAN_PERIOD + 5, STOCH_PERIOD + STOCH_SMOOTH + 5, EMA_SLOW + 5, ATR_PERIOD + 5)
    seed = SEED
    trades = []
    position = None
    last_close_ts = None
    max_hold_ms = int(max_hold_h * 3600 * 1000)
    cooldown_ms = int(cooldown_h * 3600 * 1000)

    i = warmup
    while i < n - 1:
        c = candles[i]
        if position is not None:
            entry = position["entry"]
            side = position["side"]
            hi, lo = high[i], low[i]
            exit_price, reason = None, None
            sl_price, tp_price = position["sl_price"], position["tp_price"]
            if side == "long":
                if lo <= sl_price:
                    exit_price, reason = sl_price, "SL"
                elif hi >= tp_price:
                    exit_price, reason = tp_price, "TP"
            else:
                if hi >= sl_price:
                    exit_price, reason = sl_price, "SL"
                elif lo <= tp_price:
                    exit_price, reason = tp_price, "TP"

            if exit_price is None and (c["ts"] - position["entry_ts"]) >= max_hold_ms:
                exit_price, reason = close[i], "Timeout"

            if exit_price is not None:
                raw_pct = (exit_price - entry) / entry if side == "long" else (entry - exit_price) / entry
                notional = position["notional"]
                pnl = notional * raw_pct - notional * FEE_RATE * 2
                seed += pnl
                trades.append({"profit": pnl, "pct": raw_pct * 100, "reason": reason,
                                "hold_h": (c["ts"] - position["entry_ts"]) / 3_600_000})
                last_close_ts = c["ts"]
                position = None
            i += 1
            continue

        if last_close_ts is not None and (c["ts"] - last_close_ts) < cooldown_ms:
            i += 1
            continue

        signal = entry_fn(ind, i)
        if signal:
            entry_price = close[i]
            if sl_mode == "atr" and not np.isnan(atr[i]) and atr[i] > 0:
                sl_dist = atr[i] * sl_atr_mult
            else:
                sl_dist = entry_price * sl_pct / 100
            tp_dist = entry_price * tp_pct / 100

            if signal == "long":
                sl_price = entry_price - sl_dist
                tp_price = entry_price + tp_dist
            else:
                sl_price = entry_price + sl_dist
                tp_price = entry_price - tp_dist

            notional = seed * ENTRY_PERCENT * LEVERAGE
            position = {"side": signal, "entry": entry_price, "entry_ts": c["ts"],
                        "sl_price": sl_price, "tp_price": tp_price, "notional": notional}
        i += 1

    return trades, seed


def quick_stats(trades, final_seed):
    n = len(trades)
    if n == 0:
        return "거래 없음"
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
    avg_win_pct = sum(t["pct"] for t in wins) / len(wins) if wins else 0
    avg_loss_pct = sum(t["pct"] for t in losses) / len(losses) if losses else 0
    avg_hold = sum(t["hold_h"] for t in trades) / n
    return (f"거래{n:>4}건 승률{win_rate:5.1f}% PF{pf:5.2f} 수익률{total_return:+9.2f}% "
            f"MDD{mdd:5.1f}%  평균익{avg_win_pct:+.2f}% 평균손{avg_loss_pct:+.2f}% 평균보유{avg_hold:4.1f}h")


VARIANTS = [
    # (label, entry_key, tp_pct, sl_mode, sl_atr_mult, sl_pct, max_hold_h)
    ("EMA눌림목 TP1.0 SL=ATR*1.5",   "EMA눌림목", 1.0, "atr", 1.5, None, 24),
    ("EMA눌림목 TP1.0 SL=ATR*1.0",   "EMA눌림목", 1.0, "atr", 1.0, None, 24),
    ("EMA눌림목 TP0.7 SL=ATR*1.0",   "EMA눌림목", 0.7, "atr", 1.0, None, 24),
    ("스토캐스틱 TP1.0 SL=ATR*1.5",  "스토캐스틱", 1.0, "atr", 1.5, None, 24),
    ("스토캐스틱 TP1.0 SL=ATR*1.0",  "스토캐스틱", 1.0, "atr", 1.0, None, 24),
    ("돈치안돌파 TP1.0 SL=ATR*1.5",  "돈치안돌파", 1.0, "atr", 1.5, None, 24),
    ("돈치안돌파 TP1.0 SL=ATR*2.0",  "돈치안돌파", 1.0, "atr", 2.0, None, 24),
    ("돈치안돌파 TP1.5 SL=ATR*1.5",  "돈치안돌파", 1.5, "atr", 1.5, None, 24),
]

if __name__ == "__main__":
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]
    results = {label: [] for label, *_ in VARIANTS}

    for sym in coins:
        tf_label = "1시간봉" if INTERVAL == "60" else f"{INTERVAL}분봉"
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 {tf_label} 데이터 수집 중...", flush=True)
        candles = bcl.fetch_klines(sym, INTERVAL, DAYS)
        print(f"캔들 {len(candles)}개 수집 완료", flush=True)
        ind = compute_indicators(candles)

        print(f"\n--- {sym} 대체 진입신호 비교 ({tf_label}) ---")
        for label, entry_key, tp, sl_mode, sl_atr_mult, sl_pct, mh in VARIANTS:
            trades, seed = run_backtest(candles, ind, ENTRY_FUNCS[entry_key], tp_pct=tp,
                                         sl_mode=sl_mode, sl_atr_mult=sl_atr_mult,
                                         sl_pct=sl_pct or 1.5, max_hold_h=mh)
            total_return = (seed - SEED) / SEED * 100
            results[label].append(total_return)
            print(f"  {label}: {quick_stats(trades, seed)}", flush=True)

    print(f"\n\n=== 코인 평균 수익률 ===")
    for label, *_ in VARIANTS:
        avg = sum(results[label]) / len(results[label]) if results[label] else 0
        print(f"  {label}: 평균 {avg:+.2f}%  (개별: {['%+.2f%%' % r for r in results[label]]})")

    print("\n\n=== ALT ENTRY SIGNAL SEARCH COMPLETE ===", flush=True)
