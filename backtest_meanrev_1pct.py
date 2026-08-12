"""2026-08-12 실험: "1%를 자주, 안정적으로" 먹기 위한 완전히 새로운 진입 신호 탐색.

배경: backtest_hard_tp_1h_v2.py에서 "기존 스퀴즈+HMA200 추세추종 진입 시그널"에 청산만
hard_tp(고정 1%)로 씌워봤더니 평균적으로 손해였음 - 그 진입 신호 자체가 "추세를 끝까지
크게 먹는" 걸 전제로 설계돼서, 1%에서 끊으면 큰 승리 트레이드(특히 ETH)를 스스로 잘라먹는
문제였음.

그래서 이번엔 진입 신호 자체를 바꿔서 테스트: RSI 과매도/과매수 + 볼린저밴드 이탈이라는
"평균회귀(mean-reversion)" 방식. 원래 짧게 먹고 빠지는 성격이라 고정 1% 익절과 궁합이
좋을 것이라는 가설.

지표는 전부 벡터화(pandas/numpy)로 사전계산 - 기존 backtest_current_live.py처럼 매 캔들마다
파이썬 루프로 윈도우를 재계산하지 않음 (그래서 훨씬 빠름).

진입: RSI(14)가 과매도/과매수 진입 + (옵션) BB 상하단 이탈 + (옵션) HTF추세필터(HMA200/600,
      되돌림 방향 = 큰 추세와 같은 쪽만) + (옵션) ADX 상한(횡보장에서만)
청산: 고정 TP(%) 무조건 익절 / 고정 SL(%) / 최대 보유시간 초과시 강제청산(타임아웃)

1h, 365일, XRP/ETH/BTC/SOL만(ADA/NEAR 제외, 캐시된 데이터 사용).

사용법: python backtest_meanrev_1pct.py [SYMBOL] [DAYS] [SYMBOL2 ...]
"""
import sys

import numpy as np
import pandas as pd

import backtest_current_live as bcl

DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else bcl.DAYS
INTERVAL = "15"  # 2026-08-12: 사용자 지시로 1시간봉 대신 15분봉 고정 사용

RSI_PERIOD = 14
BB_PERIOD = 20
ADX_PERIOD = 14
HMA_FAST, HMA_SLOW = 200, 600

SEED = bcl.SEED
LEVERAGE = bcl.LEVERAGE
ENTRY_PERCENT = bcl.ENTRY_PERCENT
FEE_RATE = bcl.FEE_RATE


def wma_vec(series, period):
    weights = np.arange(1, period + 1, dtype=float)
    wsum = weights.sum()
    return series.rolling(period).apply(lambda x: np.dot(x, weights) / wsum, raw=True)


def hma_vec(close, period):
    half = max(1, period // 2)
    sq = max(1, int(np.sqrt(period)))
    wma1 = wma_vec(close, half)
    wma2 = wma_vec(close, period)
    diff = 2 * wma1 - wma2
    return wma_vec(diff, sq)


def compute_indicators(candles):
    close = pd.Series([c["close"] for c in candles])
    high = pd.Series([c["high"] for c in candles])
    low = pd.Series([c["low"] for c in candles])

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / RSI_PERIOD, adjust=False, min_periods=RSI_PERIOD).mean()
    avg_loss = loss.ewm(alpha=1 / RSI_PERIOD, adjust=False, min_periods=RSI_PERIOD).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - 100 / (1 + rs)

    sma = close.rolling(BB_PERIOD).mean()
    std = close.rolling(BB_PERIOD).std(ddof=0)
    bb_upper = sma + 2 * std
    bb_lower = sma - 2 * std

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / ADX_PERIOD, adjust=False, min_periods=ADX_PERIOD).mean()
    plus_di = 100 * pd.Series(plus_dm).ewm(alpha=1 / ADX_PERIOD, adjust=False, min_periods=ADX_PERIOD).mean() / atr
    minus_di = 100 * pd.Series(minus_dm).ewm(alpha=1 / ADX_PERIOD, adjust=False, min_periods=ADX_PERIOD).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.ewm(alpha=1 / ADX_PERIOD, adjust=False, min_periods=ADX_PERIOD).mean()

    hma_fast = hma_vec(close, HMA_FAST)
    hma_slow = hma_vec(close, HMA_SLOW)
    trend = pd.Series(np.where(hma_fast > hma_slow, "up", np.where(hma_fast < hma_slow, "down", None)))

    return {
        "close": close.values, "high": high.values, "low": low.values,
        "rsi": rsi.values, "bb_upper": bb_upper.values, "bb_lower": bb_lower.values,
        "adx": adx.values, "trend": trend.values,
    }


def run_meanrev(candles, ind, rsi_oversold=30, rsi_overbought=70, require_bb=True,
                 use_trend_filter=False, adx_max=None, tp_pct=1.0, sl_pct=1.5,
                 max_hold_h=48, cooldown_h=2.0):
    n = len(candles)
    rsi, bb_u, bb_l, adx, trend = ind["rsi"], ind["bb_upper"], ind["bb_lower"], ind["adx"], ind["trend"]
    close, high, low = ind["close"], ind["high"], ind["low"]

    warmup = max(HMA_SLOW + 50, BB_PERIOD + 5, RSI_PERIOD + 5)
    seed = SEED
    trades = []
    position = None
    last_close_ts = None
    max_hold_ms = int(max_hold_h * 3600 * 1000)  # 타임스탬프 기준(타임프레임 무관하게 정확)
    cooldown_ms = int(cooldown_h * 3600 * 1000)

    i = warmup
    while i < n - 1:
        c = candles[i]
        if position is not None:
            entry = position["entry"]
            side = position["side"]
            hi, lo = high[i], low[i]
            exit_price, reason = None, None
            if side == "long":
                sl_price = entry * (1 - sl_pct / 100)
                tp_price = entry * (1 + tp_pct / 100)
                if lo <= sl_price:
                    exit_price, reason = sl_price, "SL"
                elif hi >= tp_price:
                    exit_price, reason = tp_price, "TP"
            else:
                sl_price = entry * (1 + sl_pct / 100)
                tp_price = entry * (1 - tp_pct / 100)
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

        if np.isnan(rsi[i]) or np.isnan(bb_u[i]) or np.isnan(bb_l[i]):
            i += 1
            continue

        signal = None
        if rsi[i] < rsi_oversold:
            signal = "long"
        elif rsi[i] > rsi_overbought:
            signal = "short"

        if signal and require_bb:
            if signal == "long" and close[i] > bb_l[i]:
                signal = None
            elif signal == "short" and close[i] < bb_u[i]:
                signal = None

        if signal and use_trend_filter:
            t = trend[i]
            if signal == "long" and t != "up":
                signal = None
            elif signal == "short" and t != "down":
                signal = None

        if signal and adx_max is not None:
            if np.isnan(adx[i]) or adx[i] > adx_max:
                signal = None

        if signal:
            entry_price = close[i]
            notional = seed * ENTRY_PERCENT * LEVERAGE
            position = {"side": signal, "entry": entry_price, "entry_idx": i,
                        "entry_ts": c["ts"], "notional": notional}

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
    # (label, rsi_os, rsi_ob, require_bb, trend_filter, adx_max, tp, sl, max_hold_h)
    ("A: RSI만(30/70) TP1.0 SL1.5",              30, 70, False, False, None, 1.0, 1.5, 48),
    ("B: RSI+BB이탈 TP1.0 SL1.5",                 30, 70, True,  False, None, 1.0, 1.5, 48),
    ("C: RSI+BB+추세필터(순응) TP1.0 SL1.5",       30, 70, True,  True,  None, 1.0, 1.5, 48),
    ("D: RSI+BB+ADX<25(횡보장) TP1.0 SL1.5",       30, 70, True,  False, 25,   1.0, 1.5, 48),
    ("E: RSI+BB+추세필터 TP0.7 SL1.2",             30, 70, True,  True,  None, 0.7, 1.2, 48),
    ("F: RSI+BB+추세필터 TP1.5 SL2.0",             30, 70, True,  True,  None, 1.5, 2.0, 48),
    ("G: RSI(25/75)+BB+추세필터 TP1.0 SL1.5",      25, 75, True,  True,  None, 1.0, 1.5, 48),
]

if __name__ == "__main__":
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]
    results = {label: [] for label, *_ in VARIANTS}

    for sym in coins:
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 15분봉 데이터 수집 중...", flush=True)
        candles = bcl.fetch_klines(sym, INTERVAL, DAYS)
        print(f"캔들 {len(candles)}개 수집 완료", flush=True)
        ind = compute_indicators(candles)

        print(f"\n--- {sym} 평균회귀(mean-reversion) 진입 신호 비교 (15분봉) ---")
        for label, rsi_os, rsi_ob, req_bb, tf, adxm, tp, sl, mh in VARIANTS:
            trades, seed = run_meanrev(candles, ind, rsi_oversold=rsi_os, rsi_overbought=rsi_ob,
                                        require_bb=req_bb, use_trend_filter=tf, adx_max=adxm,
                                        tp_pct=tp, sl_pct=sl, max_hold_h=mh)
            total_return = (seed - SEED) / SEED * 100
            results[label].append(total_return)
            print(f"  {label}: {quick_stats(trades, seed)}", flush=True)

    print(f"\n\n=== 코인 평균 수익률 ===")
    for label, *_ in VARIANTS:
        avg = sum(results[label]) / len(results[label]) if results[label] else 0
        print(f"  {label}: 평균 {avg:+.2f}%  (개별: {['%+.2f%%' % r for r in results[label]]})")

    print("\n\n=== MEAN-REVERSION 1% ENTRY SEARCH COMPLETE ===", flush=True)
