"""
2026-08-11 실험: profit_lock 튜닝(profit_lock_finetune2.log)에서 ratio를 0.9→0.99로 올릴수록
총수익률이 모든 코인에서 거의 무한정 커지는 패턴(XRP +15%→+44%, ETH +59%→+102%, SOL +146%→+235%)
이 관찰됐는데, 이게 "타이트한 트레일링이 실제로 유효하다"는 신호인지 백테스트 구조상의
낙관 편향(같은 봉 안에서 신고점 → SL 타이트닝 → 그 봉의 저가로 SL 히트)인지 검증하기 위한
버전.

기존 run_backtest()(backtest_current_live.py)는 한 루프 안에서:
  1) 이번 봉의 high/low로 max_profit_price(신고점) 갱신
  2) 그 갱신된 신고점 기준으로 SL을 즉시 타이트닝(staged_sl)
  3) 같은 봉의 low(또는 high)로 그 타이트닝된 SL 히트 여부 판정
을 순서대로 수행함 → "이번 봉 안에서 신고점을 찍은 뒤 반전해서 SL을 맞았다"는 인과관계를
가정하지만, OHLC 데이터만으론 신고점(high)과 SL히트(low)가 봉 안에서 어느 순서로
일어났는지 알 수 없음(반대 순서였다면 실제로는 구 SL로 먼저 청산됐어야 함). ratio가 1에
가까울수록 이 낙관적 가정에 기대는 이득이 커지므로, 위 결과가 편향일 가능성이 높음.

이 파일의 run_backtest_lagged()는 그 인과관계를 끊음: 이번 봉의 청산 판정은 "직전 봉까지
확정된" sl_price/tp_price만 사용하고, 이번 봉의 high/low로 신고점을 갱신 → SL 타이트닝하는
건 청산 판정 "이후"에 수행해서 다음 봉부터 적용되게 함 (실제 봉마감 후에만 상태를 갱신하는
보수적/무편향 가정). 나머지 로직(단계 전환, HMA200 하드컷, HMA갭 반전 청산, BB폭 SL/TP)은
동일.
"""
import sys
from datetime import datetime

from backtest_current_live import (
    fetch_klines, width_info_at, hma_at, htf_trend_at, hma_gap_at,
    volume_confirmed_at, summarize,
    SEED, FEE_RATE, LEVERAGE, ENTRY_PERCENT, SL_PERCENT, REENTRY_COOLDOWN_MS,
    HMA_GAP_SLOW, HMA_GAP_CONTRACTION_RATIO, HMA_GAP_EXIT_BUFFER_PCT,
    MIN_PROFIT_FOR_BREAKEVEN_PCT, STAGE1_FEE_BUFFER_PCT, HMA_ENTRY_PERIOD,
    SQUEEZE_ENTER_MULT, BREAKOUT_MULT, WIDTH_FETCH_WINDOW, WIDTH_LOOKBACK,
    INTERVAL, DAYS,
)

DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else DAYS


def run_backtest_lagged(candles, hma200_buffer_pct=0.0, profit_lock_trigger_pct=None,
                         profit_lock_ratio=None, volume_mult=None):
    """run_backtest()과 동일 로직이나, 신고점 기반 SL/TP 타이트닝이 "이번 봉 청산판정 이후"에
    반영돼 다음 봉부터만 유효하도록 순서를 바꿈 (같은 봉 내 신고점→SL히트 낙관편향 제거)."""
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

        # ────────────────── 포지션 관리 ──────────────────
        if position:
            side = position["side"]
            entry = position["entry"]

            exit_price = None
            reason = None

            # 0단계(normal): 1h HMA200 반대쪽 이탈 시 즉시 청산 (+ 완충 버퍼) - HMA 자체가
            # 이미 1봉 지연(window[-2])이라 그대로 둬도 무편향
            if position["profit_mode"] == "normal":
                h200 = hma_at(candles, t, HMA_ENTRY_PERIOD)
                hma200_now = h200["hma"] if h200 else None
                if hma200_now is not None:
                    if side == "long":
                        break_level = hma200_now * (1 - hma200_buffer_pct / 100)
                        if low < break_level:
                            exit_price, reason = break_level, "HMA200 Break"
                    else:
                        break_level = hma200_now * (1 + hma200_buffer_pct / 100)
                        if high > break_level:
                            exit_price, reason = break_level, "HMA200 Break"

            # 단계 전환: normal → trend_follow (지연된 HMA200/600 정배열 - 무편향)
            if exit_price is None and position["profit_mode"] == "normal":
                trend = htf_trend_at(candles, t)
                favorable = (side == "long" and trend == "up") or (side == "short" and trend == "down")
                if favorable:
                    position["profit_mode"] = "trend_follow"
                    position["hma_gap_peak"] = 0

            # trend_follow: HMA갭 부호반전만으로 청산 판정 (SL/TP 타이트닝은 아래서 "다음봉용"으로 갱신)
            gap_info = None
            if exit_price is None and position["profit_mode"] == "trend_follow":
                gap_info = hma_gap_at(candles, t)
                if gap_info is not None:
                    gap = gap_info["gap"]
                    favorable_gap = (gap > 0) if side == "long" else (gap < 0)
                    if not favorable_gap:
                        exit_price, reason = close, "HMA Trend Reversal"

            # 청산 판정 - "직전 봉까지 확정된" sl_price/tp_price만 사용 (이번 봉 신고점 미반영)
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
                # peak_profit_pct 로깅용 - 청산 시점까지(이번 봉 포함) 실제 관측된 극값 사용
                if side == "long":
                    realized_peak = max(position["max_profit_price"], high)
                    peak_profit_pct = (realized_peak - entry) / entry * 100
                else:
                    realized_peak = min(position["max_profit_price"], low)
                    peak_profit_pct = (entry - realized_peak) / entry * 100

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

            # ── 청산 안 됐으면: 이제서야 이번 봉 high/low로 신고점 갱신 + SL/TP 재계산
            #    (다음 봉부터 적용 - 이번 봉 청산판정엔 영향 없음) ──
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

            if position["profit_mode"] == "trend_follow":
                staged_sl = None
                if peak_profit_pct >= MIN_PROFIT_FOR_BREAKEVEN_PCT:
                    staged_sl = (entry * (1 + STAGE1_FEE_BUFFER_PCT / 100) if side == "long"
                                 else entry * (1 - STAGE1_FEE_BUFFER_PCT / 100))

                if gap_info is not None:
                    gap = gap_info["gap"]
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

            if position["profit_mode"] == "normal" and is_new_high:
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

            continue  # 포지션 있던 봉에서는 같은 봉 재진입 신호 체크 생략

        # ────────────────── 진입 신호 체크 (run_backtest()과 동일) ──────────────────
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
                        htf_trend = "up" if candle_close > hma200_now else ("down" if candle_close < hma200_now else None)
                        trend_ok = (signal == "long" and htf_trend == "up") or (signal == "short" and htf_trend == "down")
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
    triggers = [2.0]
    ratios = [0.5, 0.6, 0.7, 0.85, 0.9, 0.95, 0.99]

    for sym in coins:
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 {INTERVAL}분봉(1시간봉) 데이터 수집 중...", flush=True)
        candles = fetch_klines(sym, INTERVAL, DAYS)
        print(f"캔들 {len(candles)}개 수집 완료 "
              f"({datetime.fromtimestamp(candles[0]['ts']/1000)} ~ {datetime.fromtimestamp(candles[-1]['ts']/1000)})",
              flush=True)

        trades, final_seed = run_backtest_lagged(candles)
        summarize(f"{sym} 무편향(lagged) baseline(profit_lock 없음)", trades, final_seed)

        for trig in triggers:
            for ratio in ratios:
                trades, final_seed = run_backtest_lagged(candles, profit_lock_trigger_pct=trig, profit_lock_ratio=ratio)
                summarize(f"{sym} 무편향(lagged) profit_lock trigger={trig}% ratio={ratio}", trades, final_seed)

    print("\n\n=== CAUSAL(LAGGED) TEST COMPLETE ===", flush=True)
