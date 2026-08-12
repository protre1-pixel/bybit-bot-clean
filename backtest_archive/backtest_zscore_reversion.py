"""
평균회귀(Z-Score) 전략 백테스트 - "시그널 극강 최종본 V6" 관찰 기반 추론 구현 (2026-08-05)

전제: 이 지표는 소스코드가 잠겨있어서(INVITE-ONLY) 정확한 수식을 알 수 없음.
설정창 파라미터(길이=20, Upper/Lower Threshold=±1.5, 피어리어드=20,
Standard Deviation Multiplier for TP=2.5)와 실제 차트에 찍힌 신호 위치
(저점에서 롱/고점에서 숏, 반대쪽 극점에서 TP)를 관찰해서 추론한 로직을
그대로 파이썬으로 구현한 것 — "이 지표를 똑같이 복제했다"가 아니라
"이런 로직이면 이런 결과가 나온다"는 가설 검증용 백테스트임.

가정한 로직:
  z = (close - SMA(close, Length)) / STD(close, Length)
  Long 진입: z가 Lower Threshold(-1.5) 아래로 내려갈 때 (과매도)
  Short 진입: z가 Upper Threshold(1.5) 위로 올라갈 때 (과매수)
  TP: 가격이 SMA(Period) ± (StdMultTP × STD(Period)) 밴드에 닿을 때
  SL: 지표 화면엔 SL 마커가 안 보였음 -> 두 버전으로 비교
      A) NO_SL: TP 또는 반대신호 발생 시에만 청산 (지표가 보여주는 그대로)
      B) WITH_SL: 진입가 기준 대칭적으로 TP와 동일 거리에 안전판 SL 추가

포지션 사이징/수수료/레버리지는 기존 봇 백테스트(backtest_bb_squeeze.py)와
동일하게 맞춰서 비교 가능하게 함 (entry_percent=75%, leverage=10x, fee=0.055%/side).
"""
import sys
import time
import numpy as np
import pandas as pd
from datetime import datetime
from pybit.unified_trading import HTTP

SYMBOL = sys.argv[1].upper() if len(sys.argv) > 1 else "BTCUSDT"
DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 180
INTERVAL = sys.argv[3] if len(sys.argv) > 3 else "15"  # 봇 기본값 15분봉, 인자로 override 가능 (예: "60" = 1시간봉)

LENGTH = 20
UPPER_TH = 1.5
LOWER_TH = -1.5
PERIOD = 20
TP_STD_MULT = 2.5

# 진입 신호는 그대로 두고 TP/SL만 고정 비율로 바꿔보는 버전용 (봇 지갑 기본값과 동일 비율)
FIXED_TP_PCT = 0.02
FIXED_SL_PCT = 0.015

ENTRY_PERCENT = 0.75
LEVERAGE = 10
SEED = 1000.0
FEE_RATE = 0.00055
REENTRY_COOLDOWN_SEC = 0  # 지표엔 쿨다운 개념이 안 보여서 일단 0 (반대신호/TP로만 제한)

client = HTTP(testnet=False)


def fetch_klines(symbol, interval, days):
    end_ts = int(time.time() * 1000)
    all_rows = {}
    ms_per_day = 86400_000
    start_ts = end_ts - days * ms_per_day
    cursor = end_ts
    while cursor > start_ts:
        resp = client.get_kline(category="linear", symbol=symbol, interval=interval, limit=1000, end=cursor)
        rows = resp["result"]["list"]
        if not rows:
            break
        for r in rows:
            ts = int(r[0])
            all_rows[ts] = {"ts": ts, "open": float(r[1]), "high": float(r[2]),
                             "low": float(r[3]), "close": float(r[4])}
        oldest = min(int(r[0]) for r in rows)
        if oldest >= cursor:
            break
        cursor = oldest - 1
        if len(rows) < 1000:
            break
    return [all_rows[k] for k in sorted(all_rows.keys()) if all_rows[k]["ts"] >= start_ts]


def build_indicators(candles):
    close = pd.Series([c["close"] for c in candles])
    sma_len = close.rolling(LENGTH).mean()
    std_len = close.rolling(LENGTH).std()
    z = (close - sma_len) / std_len

    sma_p = close.rolling(PERIOD).mean()
    std_p = close.rolling(PERIOD).std()
    upper_tp = sma_p + TP_STD_MULT * std_p
    lower_tp = sma_p - TP_STD_MULT * std_p

    return z.values, upper_tp.values, lower_tp.values


def signal_now(prev_z, zt, mode):
    """entry_mode='breach': z가 threshold를 뚫고 극단으로 '들어가는' 순간 (원래 구현, 반등 확인 전).
    entry_mode='confirm': z가 극단에 있다가 threshold 안쪽으로 '돌아오는' 순간 (저점/고점 형성 후 반등 확인).
    """
    if mode == "breach":
        if prev_z >= LOWER_TH > zt:
            return "long"
        elif prev_z <= UPPER_TH < zt:
            return "short"
    else:  # confirm
        if prev_z < LOWER_TH <= zt:
            return "long"
        elif prev_z > UPPER_TH >= zt:
            return "short"
    return None


def run_backtest(candles, z, upper_tp, lower_tp, use_sl=False, sl_first=True, fixed_pct=False,
                  use_opposite_exit=True, max_hold_bars=None, entry_mode="breach"):
    if fixed_pct:
        use_sl = True  # 고정 비율 모드는 TP/SL이 항상 둘 다 정의됨
    seed = SEED
    position = None
    trades = []
    prev_z = None

    start = max(LENGTH, PERIOD) + 1

    for t in range(start, len(candles)):
        c = candles[t]
        zt = z[t]
        if np.isnan(zt) or np.isnan(upper_tp[t]) or np.isnan(lower_tp[t]):
            prev_z = zt
            continue

        # ---- 포지션 관리 ----
        if position:
            side = position["side"]
            tp_price = position["tp_price"]
            sl_price = position.get("sl_price")

            tp_hit = sl_hit = False
            exit_price = reason = None

            if side == "long":
                if use_sl and sl_price is not None and c["low"] <= sl_price and c["high"] >= tp_price:
                    if sl_first:
                        sl_hit, exit_price, reason = True, sl_price, "Stop Loss"
                    else:
                        tp_hit, exit_price, reason = True, tp_price, "Take Profit"
                elif use_sl and sl_price is not None and c["low"] <= sl_price:
                    sl_hit, exit_price, reason = True, sl_price, "Stop Loss"
                elif c["high"] >= tp_price:
                    tp_hit, exit_price, reason = True, tp_price, "Take Profit"
            else:  # short
                if use_sl and sl_price is not None and c["high"] >= sl_price and c["low"] <= tp_price:
                    if sl_first:
                        sl_hit, exit_price, reason = True, sl_price, "Stop Loss"
                    else:
                        tp_hit, exit_price, reason = True, tp_price, "Take Profit"
                elif use_sl and sl_price is not None and c["high"] >= sl_price:
                    sl_hit, exit_price, reason = True, sl_price, "Stop Loss"
                elif c["low"] <= tp_price:
                    tp_hit, exit_price, reason = True, tp_price, "Take Profit"

            # 반대 방향 신호가 뜨면 그걸로도 청산 (지표가 반대 신호를 또 찍으면 실질적 청산 트리거로 간주)
            opp_sig = signal_now(prev_z, zt, entry_mode) if (use_opposite_exit and prev_z is not None) else None
            opposite_signal = (
                (side == "long" and opp_sig == "short") or
                (side == "short" and opp_sig == "long")
            )

            if not (tp_hit or sl_hit) and opposite_signal:
                exit_price, reason = c["close"], "Opposite Signal"
                tp_hit = True  # 정산 처리용 플래그 재사용

            time_stop = (not (tp_hit or sl_hit) and max_hold_bars is not None
                         and (t - position["entry_t"]) >= max_hold_bars)
            if time_stop:
                exit_price, reason = c["close"], "Time Stop"
                tp_hit = True

            if tp_hit or sl_hit:
                pnl_pct = (exit_price - position["entry"]) / position["entry"]
                if side == "short":
                    pnl_pct = -pnl_pct
                nominal = seed * ENTRY_PERCENT * LEVERAGE
                gross = nominal * pnl_pct
                fees = nominal * FEE_RATE * 2
                net = gross - fees
                seed += net
                trades.append({"side": side, "entry": position["entry"], "exit": exit_price,
                                "reason": reason, "profit": net, "profit_pct": pnl_pct * 100 * LEVERAGE})
                position = None

        # ---- 신규 진입 체크 (Threshold 상향/하향 돌파 시점에만, flat일 때만) ----
        if not position and prev_z is not None:
            signal = signal_now(prev_z, zt, entry_mode)

            if signal:
                entry_price = c["close"]
                if fixed_pct:
                    if signal == "long":
                        tp_price = entry_price * (1 + FIXED_TP_PCT)
                        sl_price = entry_price * (1 - FIXED_SL_PCT)
                    else:
                        tp_price = entry_price * (1 - FIXED_TP_PCT)
                        sl_price = entry_price * (1 + FIXED_SL_PCT)
                else:
                    tp_price = upper_tp[t] if signal == "long" else lower_tp[t]
                    sl_price = None
                    if use_sl:
                        tp_dist = abs(tp_price - entry_price)
                        sl_price = entry_price - tp_dist if signal == "long" else entry_price + tp_dist
                position = {"side": signal, "entry": entry_price, "tp_price": tp_price, "sl_price": sl_price,
                            "entry_t": t}

        prev_z = zt

    return trades, seed


def summarize(label, trades, final_seed):
    n = len(trades)
    if n == 0:
        print(f"\n=== {label} ===\n거래 없음")
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
        mdd = max(mdd, (peak - v) / peak * 100)

    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1

    print(f"\n=== {label} ===")
    print(f"거래수: {n}  승률: {win_rate:.1f}%  PF: {pf:.2f}")
    print(f"총수익률: {total_return:+.2f}%  최종시드: ${final_seed:.2f}  MDD: {mdd:.2f}%")
    print(f"종료사유: {reasons}")


if __name__ == "__main__":
    print(f"[{SYMBOL}] {DAYS}일치 {INTERVAL}분봉 데이터 수집 중...")
    candles = fetch_klines(SYMBOL, INTERVAL, DAYS)
    print(f"캔들 {len(candles)}개 수집 완료 "
          f"({datetime.fromtimestamp(candles[0]['ts']/1000)} ~ {datetime.fromtimestamp(candles[-1]['ts']/1000)})")

    z, upper_tp, lower_tp = build_indicators(candles)

    for use_sl in (False, True):
        for sl_first in ((True,) if not use_sl else (True, False)):
            label = f"{'WITH_SL' if use_sl else 'NO_SL(지표 그대로)'}" + (f" [{'sl_first' if sl_first else 'tp_first'}]" if use_sl else "")
            trades, final_seed = run_backtest(candles, z, upper_tp, lower_tp, use_sl=use_sl, sl_first=sl_first)
            summarize(label, trades, final_seed)

    for sl_first in (True, False):
        label = f"FIXED_TPSL(2.0%/1.5%, 진입신호만 지표) [{'sl_first' if sl_first else 'tp_first'}]"
        trades, final_seed = run_backtest(candles, z, upper_tp, lower_tp, sl_first=sl_first, fixed_pct=True)
        summarize(label, trades, final_seed)

    # ---- 가설 검증: "반대신호까지 존버" 규칙을 빼면 나아지는가? ----
    trades, final_seed = run_backtest(candles, z, upper_tp, lower_tp, sl_first=True, fixed_pct=True,
                                       use_opposite_exit=False)
    summarize("FIXED_TPSL, Opposite Exit 제거 (TP/SL로만 청산)", trades, final_seed)

    # ---- 가설 검증: 반대신호도 빼고 + 최대 보유기간(1일=96봉) 타임스탑까지 추가하면? ----
    trades, final_seed = run_backtest(candles, z, upper_tp, lower_tp, sl_first=True, fixed_pct=True,
                                       use_opposite_exit=False, max_hold_bars=96)
    summarize("FIXED_TPSL, Opposite Exit 제거 + 1일 타임스탑", trades, final_seed)

    # ======================================================================
    # 가설 검증: 진입 트리거 방향 자체를 잘못 잡았을 가능성
    # 지금까지: entry_mode="breach" -> z가 threshold를 뚫고 "극단으로 들어가는" 순간 진입
    #           (=가격이 아직 더 떨어지는/오르는 중일 수 있음, 저점/고점 형성 "전")
    # "저점에서 롱/고점에서 숏"이라는 관찰과 더 맞는 대안: entry_mode="confirm"
    #           -> z가 극단에 있다가 threshold 안쪽으로 "돌아오는" 순간 진입
    #           (=반등이 이미 시작된 뒤, 저점/고점 형성 "후" 확인 진입)
    # ======================================================================
    print("\n" + "=" * 70)
    print("진입 트리거 방향 비교: BREACH(돌파 즉시 진입) vs CONFIRM(반등 확인 후 진입)")
    print("=" * 70)

    for use_sl in (False, True):
        label = f"[CONFIRM] {'WITH_SL' if use_sl else 'NO_SL(지표 그대로)'}"
        trades, final_seed = run_backtest(candles, z, upper_tp, lower_tp, use_sl=use_sl, sl_first=True,
                                           entry_mode="confirm")
        summarize(label, trades, final_seed)

    trades, final_seed = run_backtest(candles, z, upper_tp, lower_tp, sl_first=True, fixed_pct=True,
                                       entry_mode="confirm")
    summarize("[CONFIRM] FIXED_TPSL(2.0%/1.5%)", trades, final_seed)

    trades, final_seed = run_backtest(candles, z, upper_tp, lower_tp, sl_first=True, fixed_pct=True,
                                       entry_mode="confirm", use_opposite_exit=False)
    summarize("[CONFIRM] FIXED_TPSL(2.0%/1.5%), Opposite Exit 제거", trades, final_seed)
