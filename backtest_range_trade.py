"""2026-08-11 실험: 박스권(레인지) 매매 - 스퀴즈+HMA200(추세추종)과 완전히 다른 철학.

가설: BTC/ADA/NEAR가 스퀴즈 임계값을 아무리 바꿔도, ADX 필터를 걸어도 계속 나빴던 건
"추세추종 전략인데 얘네가 이 기간 동안 주로 레인지(횡보)였기 때문"일 수 있다.
그렇다면 추세를 쫓는 대신, 박스 상단에서 숏/하단에서 롱으로 왕복을 먹는 평균회귀
전략이 오히려 이 코인들에 맞을 수 있다.

박스 정의: 직전 LOOKBACK개 완성캔들의 최고가/최저가 (Donchian 채널과 동일 방식).
진입 조건: ADX(14) < ADX_MAX(레인지 레짐 확인) + 종가가 박스 상/하단 EDGE_TOUCH_PCT
이내일 때만. 박스가 수수료도 못 건질 만큼 좁으면(MIN_BOX_WIDTH_PCT 미만) 스킵.
청산: 목표가(박스 반대편 or 중간선) 도달 시 익절, 박스 경계를 실제로 뚫고 나가면
(레인지 가설이 틀렸다는 뜻) 즉시 손절.

주의: run_backtest()(스퀴즈+HMA200)과는 완전히 별개의 진입/청산 로직 - 코드 공유는
fetch_klines, adx_at, SEED/LEVERAGE/ENTRY_PERCENT/FEE_RATE 상수뿐.

사용법: python backtest_range_trade.py [SYMBOL] [DAYS] [SYMBOL2 ...]
"""
import sys
from datetime import datetime

import backtest_current_live as bcl

DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else bcl.DAYS

SEED = bcl.SEED
FEE_RATE = bcl.FEE_RATE
LEVERAGE = bcl.LEVERAGE
ENTRY_PERCENT = bcl.ENTRY_PERCENT

LOOKBACK = 20
EDGE_TOUCH_PCT = 0.15      # 박스 상/하단 15% 이내 터치해야 신호
MIN_BOX_WIDTH_PCT = 1.5    # 박스 폭이 가격 대비 이 %는 넘어야 진입 (수수료 대비 여유)
ADX_MAX = 20                # ADX가 이 아래일 때만(레인지 레짐) 진입
SL_BUFFER_PCT = 0.8         # 박스 경계 이탈 시 SL까지의 버퍼


def box_at(candles, t, lookback=LOOKBACK):
    """직전 lookback개 완성 캔들(t-lookback..t-1) 기준 박스 상/하단."""
    if t - lookback < 0:
        return None
    window = candles[t - lookback:t]
    box_high = max(c["high"] for c in window)
    box_low = min(c["low"] for c in window)
    return box_high, box_low


def run_backtest_range(candles, lookback=LOOKBACK, edge_touch_pct=EDGE_TOUCH_PCT,
                        min_box_width_pct=MIN_BOX_WIDTH_PCT, adx_max=ADX_MAX,
                        sl_buffer_pct=SL_BUFFER_PCT, target="opposite",
                        profit_lock_trigger_pct=None, profit_lock_ratio=None):
    seed = SEED
    position = None
    trades = []

    min_start = max(lookback + 5, bcl.ADX_PERIOD * 4 + 60)

    for t in range(min_start, len(candles)):
        c = candles[t]
        ts = c["ts"]
        high, low, close = c["high"], c["low"], c["close"]

        if position:
            side = position["side"]
            entry = position["entry"]
            exit_price, reason = None, None

            # 박스 이탈(진짜 돌파) → 즉시 손절
            if side == "short" and high >= position["sl_price"]:
                exit_price, reason = position["sl_price"], "Box Break SL"
            elif side == "long" and low <= position["sl_price"]:
                exit_price, reason = position["sl_price"], "Box Break SL"

            # 목표가 도달 → 익절
            if exit_price is None:
                if side == "short" and low <= position["tp_price"]:
                    exit_price, reason = position["tp_price"], "Box TP"
                elif side == "long" and high >= position["tp_price"]:
                    exit_price, reason = position["tp_price"], "Box TP"

            # profit_lock (기존 스타일)
            if exit_price is None and profit_lock_trigger_pct is not None:
                cur_pct = ((close - entry) / entry * 100) if side == "long" else ((entry - close) / entry * 100)
                if cur_pct > position["peak_pct"]:
                    position["peak_pct"] = cur_pct
                peak = position["peak_pct"]
                if peak >= profit_lock_trigger_pct:
                    lock_pct = peak * profit_lock_ratio
                    if cur_pct < lock_pct:
                        exit_price, reason = close, "Profit Lock"

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

        # ── 진입 체크 ──
        box = box_at(candles, t, lookback)
        if box is None:
            continue
        box_high, box_low = box
        box_width = box_high - box_low
        if box_low <= 0 or box_width <= 0:
            continue
        box_width_pct = box_width / box_low * 100
        if box_width_pct < min_box_width_pct:
            continue

        adx_val = bcl.adx_at(candles, t)
        if adx_val is None or adx_val >= adx_max:
            continue

        pos_in_box = (close - box_low) / box_width

        signal = None
        if pos_in_box >= 1 - edge_touch_pct:
            signal = "short"
        elif pos_in_box <= edge_touch_pct:
            signal = "long"
        if signal is None:
            continue

        entry_price = close
        if signal == "short":
            sl_price = box_high * (1 + sl_buffer_pct / 100)
            tp_price = box_low if target == "opposite" else (box_high + box_low) / 2
        else:
            sl_price = box_low * (1 - sl_buffer_pct / 100)
            tp_price = box_high if target == "opposite" else (box_high + box_low) / 2

        notional = seed * ENTRY_PERCENT * LEVERAGE
        position = {
            "side": signal, "entry": entry_price, "entry_ts": ts,
            "sl_price": sl_price, "tp_price": tp_price, "peak_pct": 0,
            "notional": notional,
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
    print(f"  거래 {n}건, 승률 {win_rate:.1f}%, PF {pf:.2f}, 수익률 {total_return:+.2f}%, MDD {mdd:.1f}%")
    reasons = {}
    for t in trades:
        reasons.setdefault(t["reason"], []).append(t["profit"])
    for r, ps in reasons.items():
        print(f"    {r}: {len(ps)}건, 평균손익 ${sum(ps)/len(ps):.2f}")


if __name__ == "__main__":
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT", "ADAUSDT", "NEARUSDT"]

    for sym in coins:
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 1시간봉 데이터 수집 중...", flush=True)
        candles = bcl.fetch_klines(sym, "60", DAYS)
        print(f"캔들 {len(candles)}개 수집 완료", flush=True)

        trades, seed = run_backtest_range(candles, profit_lock_trigger_pct=2.0, profit_lock_ratio=0.85)
        summarize(f"{sym} 박스권매매(lookback={LOOKBACK}, edge={EDGE_TOUCH_PCT}, adx<{ADX_MAX})", trades, seed)

    print("\n\n=== RANGE TRADE TEST COMPLETE ===", flush=True)
