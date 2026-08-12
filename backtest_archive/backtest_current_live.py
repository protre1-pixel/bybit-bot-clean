"""
현재 라이브 코드(app/services/trading_service.py, 2026-08-10 최신) 그대로 재현하는 백테스트.

오늘 배포한 두 가지 변경사항을 모두 반영:
  1) trend_follow 단계의 HMA갭 수축 감지 시 SL 앵커를 current_price → max_profit_price로 수정
     (기존엔 신호가 뜬 시점엔 이미 최고점에서 밀린 뒤라 눌린 가격 근처에 SL을 다시 그어서
      최고점 수익을 거의 다 반납하는 문제가 있었음).
  2) 스퀴즈/브레이크아웃 신호(calculate_bollinger_bands/calculate_band_width_average)와
     진입필터·청산로직(HMA200/600) 전체를 15분봉 → 1시간봉으로 통일.

기존 backtest_bb_squeeze.py는 v2(2026-08-07) 시점의 "퍼센트 기반 4단계 계단식"
포지션관리를 재현하는 outdated 버전이라, 지금의 normal→trend_follow(HMA갭 기반)
구조와 안 맞아서 이 파일을 새로 작성함. 저수준 헬퍼(fetch_klines, width_info_at,
bollinger_at, wma)는 backtest_bb_squeeze.py에서 검증된 것을 그대로 재사용.

사용법: python backtest_current_live.py [SYMBOL] [DAYS]
  예) python backtest_current_live.py XRPUSDT 400
"""
import os
import sys
import time
import numpy as np
import pandas as pd
from datetime import datetime
from pybit.unified_trading import HTTP

SYMBOL = sys.argv[1].upper() if len(sys.argv) > 1 else "XRPUSDT"
DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 365
INTERVAL = "60"  # 1시간봉 - SQUEEZE_TIMEFRAME=HMA_GAP_TIMEFRAME=60(라이브와 동일)

BB_PERIOD = 30
WIDTH_LOOKBACK = 30
WIDTH_FETCH_WINDOW = 100
SQUEEZE_ENTER_MULT = 0.5
BREAKOUT_MULT = 1.5

VOLUME_MA_PERIOD = 20         # 거래량확인 필터 (2026-08-11 실험) - 클로드/bybit-bot의
VOLUME_MULT = 1.5             # strategy_volume_confirmed.py에서 검증된 파라미터 그대로 재사용

HMA_ENTRY_PERIOD = 200        # apply_entry_filters의 1h HMA200 (진입필터 + normal모드 하드청산)
HMA_GAP_FAST = 200            # trading_service.py HMA_GAP_FAST
HMA_GAP_SLOW = 600            # trading_service.py HMA_GAP_SLOW
HMA_GAP_CONTRACTION_RATIO = 0.4
HMA_GAP_EXIT_BUFFER_PCT = 0.6
MIN_PROFIT_FOR_BREAKEVEN_PCT = 0.4
STAGE1_FEE_BUFFER_PCT = 0.15

ENTRY_PERCENT = 0.75
LEVERAGE = 10
SEED = 1000.0
FEE_RATE = 0.00055          # 편도 0.055%
SL_PERCENT = 0.035          # wallet.get("sl", 3.5)/100 - 현재 라이브 기본값
REENTRY_COOLDOWN_MS = 1800 * 1000  # 30분

client = HTTP(testnet=False)


CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kline_cache")
CACHE_MAX_AGE_SEC = 14 * 24 * 3600  # 14일 이내 캐시는 재사용 (과거 완성봉은 안 바뀌므로 길게 잡음;
                                     # 최신 데이터 강제 반영하려면 kline_cache 폴더 파일 지우고 재실행)


def fetch_klines(symbol, interval, days):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(CACHE_DIR, f"{symbol}_{interval}_{days}.txt")
    if os.path.exists(cache_path) and time.time() - os.path.getmtime(cache_path) < CACHE_MAX_AGE_SEC:
        candles = []
        with open(cache_path, "r", encoding="utf-8") as f:
            next(f, None)  # 헤더 skip
            for line in f:
                parts = line.strip().split(",")
                if len(parts) != 6:
                    continue
                candles.append({
                    "ts": int(parts[0]), "open": float(parts[1]), "high": float(parts[2]),
                    "low": float(parts[3]), "close": float(parts[4]), "volume": float(parts[5]),
                })
        if candles:
            return candles

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
            all_rows[ts] = {
                "ts": ts,
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "volume": float(r[5]),
            }
        oldest = min(int(r[0]) for r in rows)
        if oldest >= cursor:
            break
        cursor = oldest - 1
        if len(rows) < 1000:
            break

    candles = [all_rows[k] for k in sorted(all_rows.keys()) if all_rows[k]["ts"] >= start_ts]
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write("ts,open,high,low,close,volume\n")
        for c in candles:
            f.write(f"{c['ts']},{c['open']},{c['high']},{c['low']},{c['close']},{c['volume']}\n")
    return candles


def width_info_at(candles, t, lookback=WIDTH_LOOKBACK, fetch_window=WIDTH_FETCH_WINDOW):
    """라이브 calculate_band_width_average() 재현."""
    lo = max(0, t - fetch_window + 1)
    window = candles[lo:t + 1]
    if len(window) < lookback + 2:
        return None

    close = np.array([c["close"] for c in window])
    widths = []
    for i in range(len(close) - lookback):
        seg = close[i:i + lookback]
        sma = np.mean(seg)
        std = np.std(seg)
        widths.append((sma + 2 * std) - (sma - 2 * std))

    if not widths:
        return None

    avg_width = float(np.mean(widths))
    current_width = float(widths[-1])
    candle_open = window[-2]["open"]
    candle_close = window[-2]["close"]
    return {"avg_width": avg_width, "current_width": current_width,
            "candle_open": candle_open, "candle_close": candle_close}


def bollinger_at(candles, t, period=BB_PERIOD):
    """라이브 calculate_bollinger_bands() 재현."""
    limit = max(period + 50, 100)
    lo = max(0, t - limit + 1)
    window = candles[lo:t + 1]
    if len(window) < period + 2:
        return None
    close = pd.Series([c["close"] for c in window])
    sma = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    upper = sma + 2 * std
    lower = sma - 2 * std

    idx = len(close) - 2
    if idx < 0 or pd.isna(sma.iloc[idx]):
        return None
    return {"width": float(upper.iloc[idx] - lower.iloc[idx]),
            "upper": float(upper.iloc[idx]), "lower": float(lower.iloc[idx]),
            "mid": float(sma.iloc[idx])}


def volume_confirmed_at(candles, t, period=VOLUME_MA_PERIOD, mult=VOLUME_MULT):
    """돌파(breakout) 캔들 = width_info_at()가 방향 판정에 쓰는 candle_open/candle_close와
    동일한 캔들(window[-2] == candles[t-1]). 그 캔들의 거래량이 직전 period개 평균 대비
    mult배 이상이어야 "진짜 돌파"로 인정. 클로드/bybit-bot(연구용 프로젝트)의
    strategy_volume_confirmed.py에서 4h 기준 유의미한 개선이 확인된 패턴을 그대로 이식."""
    idx = t - 1
    if idx < period:
        return None
    breakout_vol = candles[idx]["volume"]
    avg_vol = sum(c["volume"] for c in candles[idx - period:idx]) / period
    if avg_vol <= 0:
        return None
    return breakout_vol > avg_vol * mult


def wma(values, period):
    n = len(values)
    out = np.full(n, np.nan)
    weights = np.arange(1, period + 1)
    wsum = weights.sum()
    for i in range(period - 1, n):
        seg = values[i - period + 1:i + 1]
        out[i] = np.sum(weights * seg) / wsum
    return out


def hma_at(candles, t, period):
    """라이브 calculate_hma() 재현 (마지막 완성 캔들 기준, index -2)."""
    limit = max(period + 100, 200)
    lo = max(0, t - limit + 1)
    window = candles[lo:t + 1]
    if len(window) < period + 50:
        return None

    close = np.array([c["close"] for c in window])
    half = period // 2
    sq = int(np.sqrt(period))

    wma1 = wma(close, half)
    wma2 = wma(close, period)
    diff = 2 * wma1 - wma2
    hma_vals = wma(diff, sq)

    idx = len(close) - 2
    if idx < 0 or np.isnan(hma_vals[idx]):
        return None
    return {"hma": float(hma_vals[idx])}


def htf_trend_at(candles, t, fast=HMA_GAP_FAST, slow=HMA_GAP_SLOW):
    """라이브 get_htf_trend() 재현."""
    f = hma_at(candles, t, fast)
    s = hma_at(candles, t, slow)
    if f is None or s is None:
        return None
    if f["hma"] > s["hma"]:
        return "up"
    elif f["hma"] < s["hma"]:
        return "down"
    return None


def hma_gap_at(candles, t, fast=HMA_GAP_FAST, slow=HMA_GAP_SLOW):
    """라이브 get_hma_gap() 재현."""
    f = hma_at(candles, t, fast)
    s = hma_at(candles, t, slow)
    if f is None or s is None:
        return None
    return {"gap": f["hma"] - s["hma"], "fast": f["hma"], "slow": s["hma"]}


ADX_PERIOD = 14


def adx_at(candles, t, period=ADX_PERIOD):
    """2026-08-11 실험: 라이브에 없는 신규 레짐필터 후보 - Wilder's ADX.
    ADX가 낮으면(횡보/노이즈 구간) 스퀴즈+HMA200 신호 자체가 가짜 돌파일 확률이
    높다는 가설 검증용. 다른 지표들과 동일하게 '마지막 완성 캔들'(index t-1) 기준
    값을 반환. 데이터 부족하면 None."""
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
    if idx < 0 or pd.isna(adx.iloc[idx]):
        return None
    return float(adx.iloc[idx])


def run_backtest(candles, hma200_buffer_pct=0.0, profit_lock_trigger_pct=None, profit_lock_ratio=None,
                  volume_mult=None, adx_min=None, hard_tp_pct=None, use_hma_regime_filter=False,
                  use_price_alignment_filter=False):
    """hma200_buffer_pct: normal 단계 HMA200 Break 하드룰에 완충 버퍼(%) 추가.
    0이면 기존과 동일(HMA200을 살짝만 넘어도 즉시 청산). >0이면 그만큼 더 넘어가야 청산.

    profit_lock_trigger_pct/profit_lock_ratio: 2026-08-10 v5 제안 - trend_follow 단계에서
    peak_profit_pct가 trigger% 이상 찍히면, 그 이후로는 "최고수익 × ratio"는 반납해도 무조건
    지키는 SL 하한선을 추가(HMA갭 수축 대기와 무관하게 매틱 갱신). None이면 비활성(기존과 동일).

    volume_mult: 2026-08-11 실험 - 돌파 캔들의 거래량이 직전 VOLUME_MA_PERIOD개 평균 대비
    이 배수 이상이어야 진입 신호로 인정(volume_confirmed_at). None이면 비활성(기존과 동일).

    adx_min: 2026-08-11 실험 - 진입 시점 ADX(14)가 이 값 이상이어야("추세 레짐"일 때만)
    신호를 인정. None이면 비활성(기존과 동일).

    hard_tp_pct: 2026-08-11 실험 - "단계(normal/trend_follow) 무관하게 진입가 대비 이 %만큼
    유리하게 움직이면 무조건 즉시 익절"하는 고정 상한선. 익절이 원가+0.15%(STAGE1_FEE_BUFFER_PCT)
    에서 계속 잘리는 문제(0.4%~2% 구간 보호장치 부재) 진단 후, profit_lock 대신/추가로
    "그냥 N% 먹으면 무조건 나온다"는 제일 단순한 방식이 더 나은지 비교하기 위함.
    같은 봉에서 SL도 동시에 닿으면 보수적으로 SL을 우선. None이면 비활성(기존과 동일)."""
    seed = SEED
    position = None
    trades = []
    squeeze_status = "normal"
    squeeze_width = None
    last_close_ts = None

    # HMA_GAP_SLOW(600)이 가장 큰 warmup 요구치 - hma_at 내부에서 period+100(최소 200)개
    # 윈도우 필요 + 그 중 half/sqrt WMA들이 또 앞부분을 깎아먹으므로 넉넉히 잡음
    min_start = max(WIDTH_FETCH_WINDOW + WIDTH_LOOKBACK + 5, HMA_GAP_SLOW + 150)

    for t in range(min_start, len(candles)):
        c = candles[t]
        ts = c["ts"]
        high, low, close = c["high"], c["low"], c["close"]

        # ────────────────── 포지션 관리 ──────────────────
        if position:
            side = position["side"]
            entry = position["entry"]

            # 최고(유리한)가 갱신 - 인트라바 극값 사용
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

            # 0단계(normal): 1h HMA200 반대쪽 이탈 시 즉시 청산 (+ 완충 버퍼)
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

                # 추가: 최고수익 반납 방지 트레일링 (HMA갭 수축 대기와 무관하게 항상 체크)
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

            # 무조건 익절(hard_tp_pct): 단계 무관하게 진입가 대비 이 %만큼 유리하면 즉시 익절.
            # 같은 봉에서 SL도 닿으면 보수적으로 SL 우선.
            if exit_price is None and hard_tp_pct is not None:
                target = entry * (1 + hard_tp_pct / 100) if side == "long" else entry * (1 - hard_tp_pct / 100)
                sl_hit = (low <= position["sl_price"]) if side == "long" else (high >= position["sl_price"])
                tp_hit = (high >= target) if side == "long" else (low <= target)
                if sl_hit:
                    exit_price, reason = position["sl_price"], "Stop Loss"
                elif tp_hit:
                    exit_price, reason = target, f"Hard TP {hard_tp_pct}%"

            # 청산 판정 (SL 우선 - 보수적 가정, 같은 봉 내 SL/TP 동시도달 시)
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
            continue  # 포지션 있던/청산된 봉에서는 같은 봉 재진입 신호 체크 생략 (라이브도 순차 처리)

        # ────────────────── 진입 신호 체크 ──────────────────
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

                if signal and adx_min is not None:
                    adx_val = adx_at(candles, t)
                    if adx_val is None or adx_val < adx_min:
                        signal = None

                if signal:
                    if use_price_alignment_filter:
                        # 2026-08-12 실험: 진입 시점에 "가격 / 200 / 600" 완전 정배열(역배열)일
                        # 때만 진입 허용. 눌림목(가격이 200 아래/위로 눌린 상태) 진입 자체를 차단해서
                        # 진입 직후 "HMA200 Break" 즉시청산이 애초에 발생하지 않게 만드는 실험.
                        h200 = hma_at(candles, t, HMA_GAP_FAST)
                        h600 = hma_at(candles, t, HMA_GAP_SLOW)
                        h200v = h200["hma"] if h200 else None
                        h600v = h600["hma"] if h600 else None
                        if h200v is None or h600v is None:
                            signal = None
                        else:
                            trend_ok = (
                                (signal == "long" and candle_close > h200v > h600v) or
                                (signal == "short" and candle_close < h200v < h600v)
                            )
                            if not trend_ok:
                                signal = None
                    elif use_hma_regime_filter:
                        # 2026-08-12 실험: "가격 vs HMA200" 대신 "HMA200 vs HMA600 정배열/역배열"로
                        # 추세필터를 바꿈. 가격이 일시적으로 200선 아래(위)로 눌려도 큰 추세(200/600
                        # 골든/데드크로스)가 살아있으면 진입 허용 - 눌림목 진입 기회를 넓히려는 목적.
                        regime = htf_trend_at(candles, t)
                        trend_ok = (signal == "long" and regime == "up") or (signal == "short" and regime == "down")
                        if not trend_ok:
                            signal = None
                    else:
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


def summarize(label, trades, final_seed):
    n = len(trades)
    print(f"\n=== {label} ===")
    if n == 0:
        print("거래 없음")
        return
    wins = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] <= 0]
    win_rate = len(wins) / n * 100
    gross_win = sum(t["profit"] for t in wins)
    gross_loss = -sum(t["profit"] for t in losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    total_return = (final_seed - SEED) / SEED * 100
    avg_hold = sum(t["hold_h"] for t in trades) / n

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

    print(f"거래수: {n}  승률: {win_rate:.1f}%  PF: {pf:.2f}  평균보유: {avg_hold:.1f}h")
    print(f"총수익률: {total_return:+.2f}%  최종시드: ${final_seed:.2f}  MDD: {mdd:.2f}%")

    reasons = {}
    for t in trades:
        r = t["reason"]
        reasons.setdefault(r, []).append(t["profit"])
    print("종료사유별 breakdown:")
    reason_trades = {}
    for t in trades:
        reason_trades.setdefault(t["reason"], []).append(t)
    for r, pnls in sorted(reasons.items(), key=lambda x: -len(x[1])):
        cnt = len(pnls)
        total = sum(pnls)
        avg = total / cnt
        line = f"  {r:<22} {cnt:>3}건  합계 ${total:>9.2f}  평균 ${avg:>8.2f}"
        if r == "Trend Follow Stop":
            ts_trades = reason_trades[r]
            avg_peak = sum(t["peak_pct"] for t in ts_trades) / len(ts_trades)
            avg_actual = sum(t["pct"] for t in ts_trades) / len(ts_trades)
            line += f"  (최고수익평균 {avg_peak:+.2f}% → 청산시 {avg_actual:+.2f}%)"
        print(line)


if __name__ == "__main__":
    # 2026-08-10 v5: EPIC 실거래에서 최고+7.18% → 청산+0.04%로 거의 전액 반납된 사례 확인.
    # trend_follow의 SL이 본전락/HMA갭수축 두 이벤트 사이엔 안 움직이는 구조적 문제 → 최고수익
    # 반납방지 트레일링(profit_lock) 옵션을 추가해서 여러 코인 x 파라미터로 효과 검증.
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]
    triggers = [2.0, 3.0, 4.0]
    ratios = [0.4, 0.5, 0.6]

    for sym in coins:
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 {INTERVAL}분봉(1시간봉) 데이터 수집 중...")
        candles = fetch_klines(sym, INTERVAL, DAYS)
        print(f"캔들 {len(candles)}개 수집 완료 "
              f"({datetime.fromtimestamp(candles[0]['ts']/1000)} ~ {datetime.fromtimestamp(candles[-1]['ts']/1000)})")

        trades, final_seed = run_backtest(candles)
        summarize(f"{sym} 기준(profit_lock 없음)", trades, final_seed)

        for trig in triggers:
            for ratio in ratios:
                trades, final_seed = run_backtest(candles, profit_lock_trigger_pct=trig, profit_lock_ratio=ratio)
                summarize(f"{sym} profit_lock trigger={trig}% ratio={ratio}", trades, final_seed)
