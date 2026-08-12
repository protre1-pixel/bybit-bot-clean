"""2026-08-11 실험: normal 단계의 "HMA200 Break"(가격이 HMA200 한 줄을 스치기만 해도 즉시
손절) 하드컷을, trend_follow 단계에서 이미 쓰고 있는 "HMA갭 크로스"(HMA200 vs HMA600의
부호 반전 = 진짜 골든/데드크로스) 기준으로 통일했을 때의 효과 검증.

배경: backtest_15m.py로 진입+청산을 전부 15분봉으로 되돌려봤더니 4코인 전부 PF<1,
MDD 90%대로 붕괴. 원인 분석 결과 손실의 대부분이 "HMA200 Break"(정상단계 하드컷)에서
나왔고(15분봉에서 코인당 68~90건 vs 1시간봉 11~20건), 반면 실제 골든/데드크로스에
해당하는 "HMA Trend Reversal"(trend_follow 단계, hma_gap_at 부호반전)은 코인당 0~2건
밖에 안 됨. 즉 "가격이 HMA200 한 줄을 스치는" 조건이 "두 HMA(200/600)의 관계가 뒤집히는"
조건보다 훨씬 노이즈에 민감해서, 15분봉처럼 룩백 실시간 폭이 짧아지는 타임프레임에서
과도하게 자주 터짐.

이 파일의 run_backtest_gap_exit()는 normal 단계의 HMA200 Break 하드컷을 제거하고,
그 자리에 (trend_follow 단계와 동일한) htf_trend_at() 기반 갭 크로스 체크를 넣음:
포지션 방향과 반대로 HMA200/600 갭 부호가 뒤집히면 그 즉시 청산("HMA Gap Reversal").
나머지 로직(단계전환, trend_follow 트레일링, normal 단계 BB폭 SL/TP)은 기존과 동일.

사용법: python backtest_gap_exit.py [SYMBOL] [DAYS] [SYMBOL2 ...]
  예) python backtest_gap_exit.py XRPUSDT 400 XRPUSDT ETHUSDT BTCUSDT SOLUSDT
"""
import sys
from datetime import datetime

from backtest_current_live import (
    fetch_klines, width_info_at, hma_at, htf_trend_at, hma_gap_at,
    volume_confirmed_at, run_backtest, summarize,
    SEED, FEE_RATE, LEVERAGE, ENTRY_PERCENT, SL_PERCENT, REENTRY_COOLDOWN_MS,
    HMA_GAP_SLOW, HMA_GAP_CONTRACTION_RATIO, HMA_GAP_EXIT_BUFFER_PCT,
    MIN_PROFIT_FOR_BREAKEVEN_PCT, STAGE1_FEE_BUFFER_PCT, HMA_ENTRY_PERIOD,
    SQUEEZE_ENTER_MULT, BREAKOUT_MULT, WIDTH_FETCH_WINDOW, WIDTH_LOOKBACK,
    INTERVAL, DAYS,
)

DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else DAYS


def run_backtest_gap_exit(candles, profit_lock_trigger_pct=None, profit_lock_ratio=None,
                           volume_mult=None):
    """run_backtest()과 동일하나, normal 단계의 "HMA200 Break"(가격 vs HMA200 한 줄)
    하드컷을 "HMA Gap Reversal"(HMA200 vs HMA600 갭 부호 반전 = 골든/데드크로스)로 교체."""
    seed = SEED
    position = None
    trades = []
    squeeze_status = "normal"
    squeeze_width = None
    last_close_ts = None

    min_start = max(WIDTH_FETCH_WINDOW + WIDTH_LOOKBACK + 5, HMA_GAP_SLOW + 150)

    for t in range(min_start, len(candles)):
        c = candles[t]
        ts = c["ts"]
        high, low, close = c["high"], c["low"], c["close"]

        if position:
            side = position["side"]
            entry = position["entry"]

            if side == "long":
                if high > position["max_profit_price"]:
                    position["max_profit_price"] = high
            else:
                if low < position["max_profit_price"]:
                    position["max_profit_price"] = low
            is_new_high = position["max_profit_price"] != position["prev_max"]
            position["prev_max"] = position["max_profit_price"]
            max_profit_price = position["max_profit_price"]

            if side == "long":
                peak_profit_pct = (max_profit_price - entry) / entry * 100
            else:
                peak_profit_pct = (entry - max_profit_price) / entry * 100

            exit_price = None
            reason = None

            # 0단계(normal): HMA200/600 갭 반전(골든/데드크로스) 시 즉시 청산
            # (기존 "가격 vs HMA200 한 줄" 하드컷 대신)
            if position["profit_mode"] == "normal":
                trend = htf_trend_at(candles, t)
                unfavorable = (side == "long" and trend == "down") or (side == "short" and trend == "up")
                if unfavorable:
                    exit_price, reason = close, "HMA Gap Reversal"

            # 단계 전환: normal → trend_follow (1h HMA200/600 정배열)
            if exit_price is None and position["profit_mode"] == "normal":
                trend = htf_trend_at(candles, t)
                favorable = (side == "long" and trend == "up") or (side == "short" and trend == "down")
                if favorable:
                    position["profit_mode"] = "trend_follow"
                    position["hma_gap_peak"] = 0

            # trend_follow: 본전방어 + HMA갭 추세추종 트레일링
            if exit_price is None and position["profit_mode"] == "trend_follow":
                staged_sl = None
                if peak_profit_pct >= MIN_PROFIT_FOR_BREAKEVEN_PCT:
                    staged_sl = (entry * (1 + STAGE1_FEE_BUFFER_PCT / 100) if side == "long"
                                 else entry * (1 - STAGE1_FEE_BUFFER_PCT / 100))

                gap_info = hma_gap_at(candles, t)
                if gap_info is not None:
                    gap = gap_info["gap"]
                    favorable_gap = (gap > 0) if side == "long" else (gap < 0)
                    if not favorable_gap:
                        exit_price, reason = close, "HMA Trend Reversal"
                    else:
                        gap_abs = abs(gap)
                        gap_peak = max(position.get("hma_gap_peak", 0), gap_abs)
                        position["hma_gap_peak"] = gap_peak
                        if gap_peak > 0 and gap_abs < gap_peak * HMA_GAP_CONTRACTION_RATIO:
                            tight_sl = (max_profit_price * (1 - HMA_GAP_EXIT_BUFFER_PCT / 100) if side == "long"
                                        else max_profit_price * (1 + HMA_GAP_EXIT_BUFFER_PCT / 100))
                            if staged_sl is None:
                                staged_sl = tight_sl
                            else:
                                staged_sl = max(staged_sl, tight_sl) if side == "long" else min(staged_sl, tight_sl)

                if profit_lock_trigger_pct is not None and peak_profit_pct >= profit_lock_trigger_pct:
                    locked_pct = peak_profit_pct * profit_lock_ratio
                    profit_lock_sl = (entry * (1 + locked_pct / 100) if side == "long"
                                       else entry * (1 - locked_pct / 100))
                    if staged_sl is None:
                        staged_sl = profit_lock_sl
                    else:
                        staged_sl = max(staged_sl, profit_lock_sl) if side == "long" else min(staged_sl, profit_lock_sl)

                if staged_sl is not None:
                    if side == "long" and staged_sl > position["sl_price"]:
                        position["sl_price"] = staged_sl
                    elif side == "short" and staged_sl < position["sl_price"]:
                        position["sl_price"] = staged_sl

            # normal 모드: BB avg_width 기반 SL/TP 동적 갱신 (신고점 갱신시만)
            if exit_price is None and position["profit_mode"] == "normal" and is_new_high:
                wi = width_info_at(candles, t)
                current_bb_width = wi["avg_width"] if wi else position.get("entry_bb_width", 0)
                if side == "long":
                    new_sl = max_profit_price - current_bb_width * 0.8
                    new_tp = max_profit_price + current_bb_width
                    if new_sl > position["sl_price"]:
                        position["sl_price"] = new_sl
                    if new_tp > position["tp_price"]:
                        position["tp_price"] = new_tp
                else:
                    new_sl = max_profit_price + current_bb_width * 0.8
                    new_tp = max_profit_price - current_bb_width
                    if new_sl < position["sl_price"]:
                        position["sl_price"] = new_sl
                    if new_tp < position["tp_price"]:
                        position["tp_price"] = new_tp

            if exit_price is None:
                if position["profit_mode"] == "normal":
                    if side == "long":
                        if low <= position["sl_price"]:
                            exit_price, reason = position["sl_price"], "Stop Loss"
                        elif high >= position["tp_price"]:
                            exit_price, reason = position["tp_price"], "Take Profit"
                    else:
                        if high >= position["sl_price"]:
                            exit_price, reason = position["sl_price"], "Stop Loss"
                        elif low <= position["tp_price"]:
                            exit_price, reason = position["tp_price"], "Take Profit"
                else:
                    if side == "long":
                        if low <= position["sl_price"]:
                            exit_price, reason = position["sl_price"], "Trend Follow Stop"
                    else:
                        if high >= position["sl_price"]:
                            exit_price, reason = position["sl_price"], "Trend Follow Stop"

            if exit_price is not None:
                raw_pct = (exit_price - entry) / entry if side == "long" else (entry - exit_price) / entry
                notional = position["notional"]
                pnl = notional * raw_pct - notional * FEE_RATE * 2
                seed += pnl
                trades.append({
                    "entry_ts": position["entry_ts"], "exit_ts": ts, "side": side,
                    "entry": entry, "exit": exit_price, "profit": pnl,
                    "pct": raw_pct * 100, "reason": reason,
                    "hold_h": (ts - position["entry_ts"]) / 3_600_000,
                    "peak_pct": peak_profit_pct,
                })
                last_close_ts = ts
                position = None
            continue

        if last_close_ts is not None and (ts - last_close_ts) < REENTRY_COOLDOWN_MS:
            continue

        wi = width_info_at(candles, t)
        if wi is None:
            continue
        current_width = wi["current_width"]
        avg_width = wi["avg_width"]
        candle_open = wi["candle_open"]
        candle_close = wi["candle_close"]

        if squeeze_status == "normal":
            if current_width < avg_width * SQUEEZE_ENTER_MULT:
                squeeze_status = "squeeze"
                squeeze_width = current_width
        elif squeeze_status == "squeeze":
            if current_width < squeeze_width:
                squeeze_width = current_width

            if current_width > squeeze_width * BREAKOUT_MULT:
                signal = None
                if candle_close > candle_open:
                    signal = "long"
                elif candle_close < candle_open:
                    signal = "short"
                squeeze_status = "normal"

                if signal and volume_mult is not None:
                    vc = volume_confirmed_at(candles, t, mult=volume_mult)
                    if not vc:
                        signal = None

                if signal:
                    h200 = hma_at(candles, t, HMA_ENTRY_PERIOD)
                    hma200_now = h200["hma"] if h200 else None
                    if hma200_now is None:
                        signal = None
                    else:
                        htf_trend_entry = "up" if candle_close > hma200_now else ("down" if candle_close < hma200_now else None)
                        trend_ok = (signal == "long" and htf_trend_entry == "up") or (signal == "short" and htf_trend_entry == "down")
                        if not trend_ok:
                            signal = None

                if signal:
                    entry_price = candle_close
                    wi_entry = width_info_at(candles, t)
                    avg_w = wi_entry["avg_width"] if wi_entry else None

                    leverage_safety_pct = (1 / LEVERAGE) * 0.8
                    max_sl_distance_pct = min(SL_PERCENT, leverage_safety_pct)
                    max_sl_distance = entry_price * max_sl_distance_pct

                    if avg_w:
                        bb_width = max(avg_w, entry_price * 0.002)
                        sl_distance = min(bb_width, max_sl_distance)
                        if signal == "long":
                            tp_price = entry_price + bb_width
                            sl_price = entry_price - sl_distance
                        else:
                            tp_price = entry_price - bb_width
                            sl_price = entry_price + sl_distance
                        entry_bb_width = avg_w
                    else:
                        if signal == "long":
                            tp_price = entry_price * 1.03
                            sl_price = entry_price - max_sl_distance
                        else:
                            tp_price = entry_price * 0.97
                            sl_price = entry_price + max_sl_distance
                        entry_bb_width = 0

                    notional = seed * ENTRY_PERCENT * LEVERAGE
                    position = {
                        "side": signal, "entry": entry_price, "entry_ts": ts,
                        "max_profit_price": entry_price, "prev_max": entry_price,
                        "sl_price": sl_price, "tp_price": tp_price,
                        "profit_mode": "normal", "hma_gap_peak": 0,
                        "entry_bb_width": entry_bb_width, "notional": notional,
                    }

    return trades, seed


if __name__ == "__main__":
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]

    for sym in coins:
        for interval, label in [("15", "15분봉"), ("60", "1시간봉")]:
            print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 {label} 데이터 수집 중...", flush=True)
            candles = fetch_klines(sym, interval, DAYS)
            print(f"캔들 {len(candles)}개 수집 완료 "
                  f"({datetime.fromtimestamp(candles[0]['ts']/1000)} ~ {datetime.fromtimestamp(candles[-1]['ts']/1000)})",
                  flush=True)

            trades_base, seed_base = run_backtest(candles)
            summarize(f"{sym} {label} 기존(HMA200 Break)", trades_base, seed_base)

            trades_gap, seed_gap = run_backtest_gap_exit(candles)
            summarize(f"{sym} {label} 신규(HMA갭크로스만)", trades_gap, seed_gap)

    print("\n\n=== GAP EXIT TEST COMPLETE ===", flush=True)
