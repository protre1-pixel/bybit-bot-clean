"""
2026-08-11 실험: 사용자 제안 - "신호 감지는 15분봉(빈도 회복), 방향 확정은 1시간봉 HMA200/600
정배열로 필터링, 그리고 trend_follow 진입 후에는 SL을 단계적으로 조이지 말고(본전락/HMA갭수축
타이트닝/profit_lock 전부 끔) 오직 1시간봉 HMA 갭이 완전히 반전될 때만 청산 - 순수 추세추종".

배경: EPIC 실거래에서 16:00봉에 큰 휩쏘(저가 0.4818 → 고가 0.6105)가 나서 본전락 SL에 걸려
청산됐는데, 그 휩쏘가 꺼지고 나서 원래 하락추세가 그대로 이어져 다음날 0.41대까지 감.
"SL을 단계적으로 당기는 방식 자체가 추세를 따라가기도 전에 끊어버리는 게 다반사 아니냐"는
가설 검증용. SL을 아예 꺼버리면 진짜 추세는 더 오래 타지만, 반대로 휩쏘/눌림에서 더 크게
반납하거나 손실이 커질 위험도 있음 - 그 트레이드오프를 실측.

dual-timeframe: 신호/체결 가격은 15분봉(고빈도, 세밀한 SL 체크), HMA200/600 정배열·HMA갭
추세추종은 1시간봉(기존과 동일 로직) - 두 타임프레임을 시각 매핑해서 사용.

사용법: python backtest_dual_tf.py [SYMBOL] [DAYS] [SYMBOL2 ...]
"""
import sys
import bisect
from datetime import datetime

from backtest_current_live import (
    fetch_klines, width_info_at, hma_at, htf_trend_at, hma_gap_at, summarize,
    SEED, FEE_RATE, LEVERAGE, ENTRY_PERCENT, SL_PERCENT, REENTRY_COOLDOWN_MS,
    HMA_GAP_FAST, HMA_GAP_SLOW, HMA_GAP_CONTRACTION_RATIO, HMA_GAP_EXIT_BUFFER_PCT,
    MIN_PROFIT_FOR_BREAKEVEN_PCT, STAGE1_FEE_BUFFER_PCT, HMA_ENTRY_PERIOD,
    SQUEEZE_ENTER_MULT, BREAKOUT_MULT,
)

DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 400
SIGNAL_INTERVAL = "15"
HTF_INTERVAL = "60"


def build_htf_index_lookup(htf_candles):
    """signal candle 타임스탬프 -> 그 시점에 관측 가능한 htf(1시간) 캔들 인덱스 매핑용."""
    htf_ts = [c["ts"] for c in htf_candles]

    def lookup(ts):
        idx = bisect.bisect_right(htf_ts, ts) - 1
        return idx if idx >= 0 else None

    return lookup


def run_backtest_dual(signal_candles, htf_candles, pure_hma_follow=False,
                       profit_lock_trigger_pct=None, profit_lock_ratio=None):
    """pure_hma_follow=True: trend_follow 단계에서 본전락/HMA갭수축타이트닝/profit_lock을
    전부 끄고, HMA갭 부호반전(HMA Trend Reversal)만으로 청산. normal 단계의 초기 보호
    (HMA200 이탈 하드컷 + BB폭 기반 SL/TP)는 유지 - trend_follow 전환 전 안전장치는 그대로 둠."""
    seed = SEED
    position = None
    trades = []
    squeeze_status = "normal"
    squeeze_width = None
    last_close_ts = None

    htf_lookup = build_htf_index_lookup(htf_candles)

    min_start = max(200, 5)  # width_info_at 자체가 내부에서 lookback 체크

    for t in range(min_start, len(signal_candles)):
        c = signal_candles[t]
        ts = c["ts"]
        high, low, close = c["high"], c["low"], c["close"]

        htf_idx = htf_lookup(ts)
        if htf_idx is None or htf_idx < HMA_GAP_SLOW + 150:
            continue  # HMA600 warmup 전

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

            # 0단계(normal): 1h HMA200 반대쪽 이탈 시 즉시 청산 - 그대로 유지(초기 보호)
            if position["profit_mode"] == "normal":
                h200 = hma_at(htf_candles, htf_idx, HMA_ENTRY_PERIOD)
                hma200_now = h200["hma"] if h200 else None
                if hma200_now is not None:
                    if side == "long":
                        if low < hma200_now:
                            exit_price, reason = hma200_now, "HMA200 Break"
                    else:
                        if high > hma200_now:
                            exit_price, reason = hma200_now, "HMA200 Break"

            # 단계 전환: normal → trend_follow (1h HMA200/600 정배열)
            if exit_price is None and position["profit_mode"] == "normal":
                trend = htf_trend_at(htf_candles, htf_idx)
                favorable = (side == "long" and trend == "up") or (side == "short" and trend == "down")
                if favorable:
                    position["profit_mode"] = "trend_follow"
                    position["hma_gap_peak"] = 0

            # trend_follow
            if exit_price is None and position["profit_mode"] == "trend_follow":
                gap_info = hma_gap_at(htf_candles, htf_idx)
                if gap_info is not None:
                    gap = gap_info["gap"]
                    favorable_gap = (gap > 0) if side == "long" else (gap < 0)
                    if not favorable_gap:
                        exit_price, reason = close, "HMA Trend Reversal"
                    else:
                        gap_abs = abs(gap)
                        gap_peak = max(position.get("hma_gap_peak", 0), gap_abs)
                        position["hma_gap_peak"] = gap_peak

                if exit_price is None:
                    staged_sl = None
                    # pure_hma_follow=True여도 본전락/HMA갭수축타이트닝은 계속 끔(추세를
                    # 일찍 끊는 원흉이라고 판단한 부분). 다만 profit_lock은 별도 파라미터로
                    # 켤 수 있게 분리 - "완전 무방비"와 "기존 3중 타이트닝"의 중간 지점 테스트용.
                    if not pure_hma_follow:
                        if peak_profit_pct >= MIN_PROFIT_FOR_BREAKEVEN_PCT:
                            staged_sl = (entry * (1 + STAGE1_FEE_BUFFER_PCT / 100) if side == "long"
                                         else entry * (1 - STAGE1_FEE_BUFFER_PCT / 100))

                        gap_peak = position.get("hma_gap_peak", 0)
                        if gap_info is not None:
                            gap_abs = abs(gap_info["gap"])
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
                    # pure_hma_follow=True면 staged_sl을 아예 안 건드림 -> normal 단계에서
                    # 마지막으로 세팅된 sl_price(넓은 초기 보호선)가 그대로 백스탑으로 남음

            # normal 모드: BB폭 기반 SL/TP 갱신 - 그대로 유지
            if exit_price is None and position["profit_mode"] == "normal" and is_new_high:
                wi = width_info_at(htf_candles, htf_idx)
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

        wi = width_info_at(signal_candles, t)
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

                if signal:
                    # 진입필터: 1시간봉 HMA200/600 정배열이 신호 방향과 같아야 함(사용자 제안).
                    # + 가격이 1h HMA200 유리한 쪽에 있어야 함(기존 apply_entry_filters와 동일,
                    # normal 단계의 "HMA200 이탈 즉시 청산" 하드컷과 기준을 맞추기 위해 필수 -
                    # 이게 없으면 200/600 정배열만 보고 진입했는데 가격은 이미 HMA200 반대쪽이라
                    # 바로 다음 틱에 "HMA200 Break"로 즉시 청산되면서 entry_price와 무관한
                    # hma200_now 가격으로 손익이 잡혀 비현실적인 손익이 나오는 버그가 있었음).
                    h200_entry = hma_at(htf_candles, htf_idx, HMA_ENTRY_PERIOD)
                    hma200_now = h200_entry["hma"] if h200_entry else None
                    trend = htf_trend_at(htf_candles, htf_idx)
                    trend_ok = (signal == "long" and trend == "up") or (signal == "short" and trend == "down")
                    price_ok = (hma200_now is not None) and (
                        (signal == "long" and candle_close > hma200_now) or
                        (signal == "short" and candle_close < hma200_now)
                    )
                    if not (trend_ok and price_ok):
                        signal = None

                if signal:
                    entry_price = candle_close
                    wi_entry = width_info_at(htf_candles, htf_idx)
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
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 15분봉+1시간봉 데이터 수집 중...", flush=True)
        signal_candles = fetch_klines(sym, SIGNAL_INTERVAL, DAYS)
        htf_candles = fetch_klines(sym, HTF_INTERVAL, DAYS)
        print(f"15분봉 {len(signal_candles)}개 / 1시간봉 {len(htf_candles)}개 수집 완료", flush=True)

        trades, final_seed = run_backtest_dual(signal_candles, htf_candles, pure_hma_follow=False)
        summarize(f"{sym} 15분신호+1h트렌드필터 (기존 단계적 SL 유지)", trades, final_seed)

        trades, final_seed = run_backtest_dual(signal_candles, htf_candles, pure_hma_follow=True)
        summarize(f"{sym} 15분신호+1h트렌드필터 (SL무효화, HMA반전시만 청산)", trades, final_seed)

        trades, final_seed = run_backtest_dual(
            signal_candles, htf_candles, pure_hma_follow=True,
            profit_lock_trigger_pct=2.0, profit_lock_ratio=0.85,
        )
        summarize(f"{sym} 15분신호+1h트렌드필터 (본전락/갭타이트닝 끔, profit_lock만 유지)", trades, final_seed)

    print("\n\n=== DUAL-TF TEST COMPLETE ===", flush=True)
