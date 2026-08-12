"""
BB Squeeze/Breakout 전략 백테스트 (재생성본, 2026-08-05)

목적: 이번에 바꾼 "진입 타점" 로직(squeeze 저점 폭 대비 1.5배 확장 시 즉시 진입)이
기존 로직(25시간 평균 폭을 넘어야 진입)보다 실제로 나은지 비교.
동시에 Normal 모드 TP가 신고점마다 계속 멀어지는 문제(TP-recede bug)가
현재 라이브 코드(app/services/trading_service.py)에 아직 남아있는 게 확인돼서,
그 두 변수를 독립적으로 켜고 끌 수 있게 만들어서 3가지 조합을 비교한다:

  1) BASELINE : 기존 avg_width 기준 진입 + TP recede 버그 있음 (이전 세션 최초 백테스트 재현)
  2) NEW_ENTRY: squeeze_width 기준 진입(신규) + TP recede 버그 있음 (진입 타이밍만 바꾼 효과 격리)
  3) NEW_BOTH : squeeze_width 기준 진입(신규) + TP 고정(freeze) 수정 (둘 다 적용한 최선 시나리오)

라이브 코드와 최대한 동일한 파라미터만 사용 (BB period=30, width lookback=30, 표준편차
ddof=0(모집단) 통일 - 2026-08-06,
squeeze 진입 임계 0.5x, breakout 배수 1.5x, entry_percent=75%, leverage=10x,
normal 모드 SL 오프셋 0.8x, trailing 전환 5%/2%, 수수료 0.055%/side,
재진입 쿨다운 30분, symmetric TP/SL = entry_bb_width 초기값).
"""
import sys
import time
import numpy as np
import pandas as pd
from datetime import datetime
from pybit.unified_trading import HTTP

SYMBOL = sys.argv[1].upper() if len(sys.argv) > 1 else "BTCUSDT"
DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 180
INTERVAL = "15"  # 분

BB_PERIOD = 30       # 2026-08-06: 20 → 30 (사용자 확인: 1시간 이내 타임프레임은 30이 기준)
WIDTH_LOOKBACK = 30  # 2026-08-06: 라이브 코드와 동일하게 10 → 20 → 30
WIDTH_FETCH_WINDOW = 100  # 라이브 코드의 limit=max(lookback*3,100)과 동일
SQUEEZE_ENTER_MULT = 0.5
BREAKOUT_MULT = 1.5

ADX_PERIOD = 14        # 2026-08-06: v8 - HMA200 필터 대체용 ADX/+DI/-DI
ADX_CHOP_THRESHOLD = 15  # 이 미만이면 진짜 횡보로 판단, 진입 스킵 (보조 필터)

ENTRY_PERCENT = 0.75
LEVERAGE = 10
SEED = 1000.0
FEE_RATE = 0.00055  # 편도 0.055%
NORMAL_SL_MULT = 0.8
TRAILING_TRIGGER_PCT = 5.0
TRAILING_STOP_PCT = 2.0
REENTRY_COOLDOWN_SEC = 1800

# 2026-08-07: 라이브 코드(app/services/trading_service.py)의 실제 4단계 계단식
# 수익보호 로직을 그대로 재현 (기존 백테스트는 normal/trailing 2단계짜리 단순화판이라
# 실제 운영 로직과 안 맞는다는 게 확인돼서 추가함).
SL_PERCENT = 0.015     # 지갑 기본 sl% (wallet.get("sl", 1.5)/100)
STAGE1_TRIGGER_PCT = 1.0
STAGE1_FEE_BUFFER_PCT = 0.15
STAGE2_TRIGGER_PCT = 2.0
STAGE2_LOCK_RATIO = 0.5
STAGE3_TRIGGER_PCT = 5.0
STAGE3_TRAIL_RATIO = 0.3
STAGE3_TRAIL_MIN_PCT = 3.0

# 2026-08-07: 위 STAGE1~3 고정 %가 "15분봉/특정 변동성"에 맞춰진 값이라 1시간봉이나
# 변동성이 다른 코인에 그대로 쓰면 (HEI 사례처럼) 너무 타이트하게 걸린다는 게 확인됨.
# vol_scaled_stages=True일 때는 고정 %대신 "진입 시점 BB폭(%)"을 변동성 단위로 삼아
# 트리거/버퍼를 전부 이 단위의 배수로 스케일링한다. 즉 변동성이 큰 진입일수록 트리거도
# 버퍼도 비례해서 넓어짐 - 모든 값은 처음부터 튜닝된 게 아니라 "합리적인 초기 추정치".
VOL_S1_TRIGGER_MULT = 0.5     # 진입시 BB폭(%)의 0.5배 벌면 breakeven 발동
VOL_S1_BUFFER_MULT = 0.1      # breakeven SL = 진입가 + BB폭(%)의 0.1배 (trigger보다 확실히 작게)
VOL_S2_TRIGGER_MULT = 1.0     # BB폭(%)의 1.0배 벌면 partial_lock 발동
VOL_S3_TRIGGER_MULT = 2.5     # BB폭(%)의 2.5배 벌면 trailing 발동
VOL_S3_TRAIL_MIN_MULT = 0.5   # trailing 최소 반납폭 = BB폭(%)의 0.5배

# 2026-08-07: 사용자 제안 - 예전(app_backup.py)에 ATR 기반으로 하다가 BB로 넘어온 적이
# 있는데 그것도 나쁘지 않았다고 함. 지금 초기 SL폭(entry_bb_width)이 "스퀴즈 브레이크아웃
# 순간"의 BB폭이라 정의상 아직 좁은 상태라, 초반 Stop Loss 비율이 너무 높은 문제(BTC 70%
# 등)의 원인일 수 있음. ATR은 종가가 아니라 고저폭 평균이라 스퀴즈 여부와 더 독립적으로
# 움직이므로, 진입 시 TP/SL 폭 산정 기준을 BB폭 대신 ATR로 바꿔서 비교해본다.
ATR_PERIOD = 14
ATR_MULT = 1.5   # ATR * 이 배수 = TP/SL 폭 (bb_width와 비슷한 스케일로 시작, 나중에 스윕)

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
    return candles


def width_info_at(candles, t, lookback=WIDTH_LOOKBACK, fetch_window=WIDTH_FETCH_WINDOW):
    """라이브 calculate_band_width_average()를 그대로 재현.
    window = candles[t-fetch_window+1 : t+1] (마지막 100개, 부족하면 있는 만큼).
    widths[i] = close[i:i+lookback] 구간의 BB width (numpy std, ddof=0).
    avg_width = 전체 widths 평균, current_width = widths[-1].
    candle_open/close = window[-2] (마지막으로 "완성된" 캔들 취급)."""
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
    """라이브 calculate_bollinger_bands() 재현 (pandas rolling, ddof=0 - 2026-08-06 통일),
    window = 최근 period+50개(최소 100개), 마지막으로 완성된 캔들 기준(index -2)."""
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


def atr_at(candles, t, period=ATR_PERIOD):
    """price_service.py calculate_atr() 재현 (단순 rolling mean of True Range, Wilder 아님).
    window = 최근 period+50개(최소 100개), 마지막으로 완성된 캔들(index -2) 기준."""
    limit = max(period + 50, 100)
    lo = max(0, t - limit + 1)
    window = candles[lo:t + 1]
    if len(window) < period + 2:
        return None

    high = np.array([c["high"] for c in window])
    low = np.array([c["low"] for c in window])
    close = np.array([c["close"] for c in window])

    prev_close = np.roll(close, 1)
    tr1 = high - low
    tr2 = np.abs(high - prev_close)
    tr3 = np.abs(low - prev_close)
    tr = np.maximum(tr1, np.maximum(tr2, tr3))

    atr_series = pd.Series(tr).rolling(period).mean().values
    idx = len(atr_series) - 2
    if idx < 0 or idx >= len(atr_series) or pd.isna(atr_series[idx]):
        return None
    return {"atr": float(atr_series[idx])}


def adx_at(candles, t, period=ADX_PERIOD):
    """app/services/price_service.py의 calculate_adx()를 그대로 재현 (list-of-dict candles용).
    마지막으로 "완성된" 캔들(window[-2]) 기준 ADX/+DI/-DI 반환."""
    limit = max(period * 4 + 50, 200)
    lo = max(0, t - limit + 1)
    window = candles[lo:t + 1]
    if len(window) < period * 3 + 5:
        return None

    high = np.array([c["high"] for c in window])
    low = np.array([c["low"] for c in window])
    close = np.array([c["close"] for c in window])

    up_move = np.diff(high)
    down_move = -np.diff(low)
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    prev_close = close[:-1]
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - prev_close), np.abs(low[1:] - prev_close))
    )

    def wilder_smooth(arr, p):
        s = np.full(len(arr), np.nan)
        if len(arr) < p:
            return s
        s[p - 1] = np.sum(arr[:p])
        for i in range(p, len(arr)):
            s[i] = s[i - 1] - s[i - 1] / p + arr[i]
        return s

    tr_s = wilder_smooth(tr, period)
    pdm_s = wilder_smooth(plus_dm, period)
    mdm_s = wilder_smooth(minus_dm, period)

    with np.errstate(divide='ignore', invalid='ignore'):
        plus_di = 100 * pdm_s / tr_s
        minus_di = 100 * mdm_s / tr_s
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)

    first = (period - 1) + period
    if len(dx) <= first + 1:
        return None

    adx = np.full(len(dx), np.nan)
    adx[first] = np.nanmean(dx[period - 1:first + 1])
    for i in range(first + 1, len(dx)):
        adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    idx = len(dx) - 2
    if idx < 0 or idx >= len(dx):
        return None
    if np.isnan(adx[idx]) or np.isnan(plus_di[idx]) or np.isnan(minus_di[idx]):
        return None

    return {"adx": float(adx[idx]), "plus_di": float(plus_di[idx]), "minus_di": float(minus_di[idx])}


def wma(values, period):
    """app/services/price_service.py calculate_wma() 재현 (numpy 배열용)."""
    n = len(values)
    out = np.full(n, np.nan)
    weights = np.arange(1, period + 1)
    wsum = weights.sum()
    for i in range(period - 1, n):
        seg = values[i - period + 1:i + 1]
        out[i] = np.sum(weights * seg) / wsum
    return out


def hma_at(candles, t, period=200):
    """app/services/price_service.py의 calculate_hma()를 그대로 재현.
    v7에서 쓰던 "종가 vs HMA200" 방향 필터를 오늘 사용자가 다시 검토 요청해서
    ADX/DI와 직접 숫자로 비교하기 위해 백테스트에도 추가 (2026-08-06)."""
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


def run_backtest(candles, breakout_mode="squeeze", tp_mode="frozen", sl_first=True,
                  use_adx_filter=False, use_hma_filter=False, hma_period=200,
                  direct_mult=1.5, squeeze_mult=None, live_staging=False,
                  htf_trend_fn=None, vol_scaled_stages=False, skip_stage1=False,
                  entry_sizing="bb", atr_mult=ATR_MULT):
    """
    breakout_mode: "avg" (v1 구로직, avg_width 넘으면 발동)
                 | "squeeze" (v2, 스퀴즈 구간 최저점*squeeze_mult 넘으면 발동 - 노이즈에 취약함이 확인됨)
                 | "squeeze_avg" (v3, 스퀴즈 구간 동안 쌓인 폭들의 "평균"*squeeze_mult 넘으면 발동)
                 | "direct" (v9, 2026-08-06: 스퀴즈 "전제조건" 자체를 없애고 언제든
                   cw > aw*direct_mult 로 처음 올라서는 그 캔들(상향 엣지)에만 즉시 진입.
                   레벨 체크가 아니라 크로스 체크라서 폭이 넓게 유지되는 동안 매 캔들
                   재신호가 뜨는 걸 막는다.)
    tp_mode: "recede" (현재 라이브 버그, TP도 신고점마다 재설정) | "frozen" (TP 고정, SL만 트레일링)
             live_staging=True일 때는 무시됨 (normal 단계는 항상 recede가 라이브와 동일).
    direct_mult: breakout_mode="direct"일 때 cw > aw*direct_mult 트리거 배수
    squeeze_mult: breakout_mode="squeeze"|"squeeze_avg"일 때 쓰는 배수. None이면 BREAKOUT_MULT(1.5) 사용.
                  2026-08-07: XRP 04:00 진입 지연 이슈 조사 중 사용자가 "최저점 1개 고정 * 1.15"를
                  테스트해보자고 해서 조정 가능하게 뺌.
    live_staging: 2026-08-07 추가. True면 app/services/trading_service.py의 실제 4단계
                  계단식 수익보호(normal→breakeven 1%→partial_lock 2%(최고수익의 50% 확정)
                  →trailing 5%(최고수익의 30%, 최소 3% 반납 허용))와 진입 시 레버리지
                  기반 SL 상한(min(SL_PERCENT, (1/LEVERAGE)*0.8))을 그대로 재현.
                  False면 기존의 단순화된 normal/trailing 2단계 로직(라이브와 다름, 참고용으로 남겨둠).
    htf_trend_fn: 2026-08-07 추가. 상위 타임프레임(1h/4h 등) HMA200/600 정배열/역배열
                  추세 필터. 콜백 fn(candle_ts_ms) -> "up"|"down"|None 형태로 전달.
                  진입 신호가 "long"인데 fn(ts)가 "up"이 아니면(= 상위 추세와 역행) 신호
                  무시, "short"인데 "down"이 아니면 무시. None이면 필터 미적용(기존과 동일).
    vol_scaled_stages: 2026-08-07 추가. True면 STAGE1~3의 고정 % 트리거/버퍼 대신
                  "진입 시점 BB폭(%)" 단위로 스케일링된 값을 사용 (VOL_S1_TRIGGER_MULT 등).
                  live_staging=True일 때만 의미 있음. False면 기존 고정 % 그대로.
    skip_stage1: 2026-08-07 추가. 사용자 제안 - "살짝 벌면 바로 본전 잠그기"(1단계 breakeven)가
                  오히려 노이즈에 조기 청산당하는 원인일 수 있다는 가설 테스트용. True면 1단계를
                  통째로 건너뛰고 0단계(normal, TP도 살아있는 트레일링)에서 곧장 2단계(partial_lock)
                  →3단계(trailing)로만 진행. live_staging=True일 때만 의미 있음.
    entry_sizing: 2026-08-07 추가. 진입 시점 TP/SL 폭 산정 기준. "bb"(기존, BB폭 - 스퀴즈
                  브레이크아웃 순간이라 정의상 폭이 좁아 초반 SL이 타이트해지는 문제 있음)
                  | "atr"(사용자 제안 - ATR*atr_mult, 스퀴즈 여부와 독립적인 변동성 측정치).
    atr_mult: entry_sizing="atr"일 때 ATR에 곱하는 배수 (TP/SL 폭 = ATR * atr_mult).
    """
    if squeeze_mult is None:
        squeeze_mult = BREAKOUT_MULT
    seed = SEED
    position = None
    trades = []
    squeeze_status = "normal"
    squeeze_width = None      # v2용 (최저점)
    squeeze_avg = None        # v3용 (누적 평균)
    squeeze_avg_sum = None
    squeeze_avg_count = 0
    last_close_ts = None
    direct_prev_above = False  # v9용 (엣지 검출)

    min_start = WIDTH_FETCH_WINDOW + WIDTH_LOOKBACK + 5

    for t in range(min_start, len(candles)):
        c = candles[t]

        # ---- 포지션 관리 ----
        if position:
            price_high, price_low = c["high"], c["low"]
            side = position["side"]

            sl_hit = tp_hit = False
            exit_price = None
            reason = None

            if live_staging:
                # ── 라이브 4단계 계단식 수익보호 재현 ──
                old_max = position["max_profit_price"]
                if side == "long":
                    if price_high > old_max:
                        position["max_profit_price"] = price_high
                else:
                    if price_low < old_max:
                        position["max_profit_price"] = price_low
                is_new_high = position["max_profit_price"] != old_max

                if side == "long":
                    peak_profit_pct = (position["max_profit_price"] - position["entry"]) / position["entry"] * 100
                else:
                    peak_profit_pct = (position["entry"] - position["max_profit_price"]) / position["entry"] * 100

                if vol_scaled_stages:
                    # 진입 시점 BB폭(%)을 변동성 단위로 삼아 트리거/버퍼를 스케일링.
                    unit = position.get("entry_bb_pct") or STAGE1_TRIGGER_PCT
                    eff_s1_trigger = VOL_S1_TRIGGER_MULT * unit
                    eff_s1_buffer = VOL_S1_BUFFER_MULT * unit
                    eff_s2_trigger = VOL_S2_TRIGGER_MULT * unit
                    eff_s3_trigger = VOL_S3_TRIGGER_MULT * unit
                    eff_s3_trail_min = VOL_S3_TRAIL_MIN_MULT * unit
                else:
                    eff_s1_trigger = STAGE1_TRIGGER_PCT
                    eff_s1_buffer = STAGE1_FEE_BUFFER_PCT
                    eff_s2_trigger = STAGE2_TRIGGER_PCT
                    eff_s3_trigger = STAGE3_TRIGGER_PCT
                    eff_s3_trail_min = STAGE3_TRAIL_MIN_PCT

                stage_rank = {"normal": 0, "breakeven": 1, "partial_lock": 2, "trailing": 3}
                current_rank = stage_rank.get(position["profit_mode"], 0)
                target_mode = position["profit_mode"]
                if peak_profit_pct >= eff_s3_trigger and current_rank < 3:
                    target_mode = "trailing"
                elif peak_profit_pct >= eff_s2_trigger and current_rank < 2:
                    target_mode = "partial_lock"
                elif not skip_stage1 and peak_profit_pct >= eff_s1_trigger and current_rank < 1:
                    target_mode = "breakeven"
                position["profit_mode"] = target_mode

                staged_sl = None
                if target_mode == "breakeven":
                    staged_sl = (position["entry"] * (1 + eff_s1_buffer / 100) if side == "long"
                                 else position["entry"] * (1 - eff_s1_buffer / 100))
                    # 2026-08-07 버그수정: STAGE1_FEE_BUFFER_PCT가 STAGE1_TRIGGER_PCT보다 크면
                    # staged_sl이 이 캔들이 실제로 도달한 최고가(max_profit_price)보다 높게(long
                    # 기준) 계산될 수 있음. 그러면 바로 아래 price_low<=sl_price 체크가 "가격이
                    # 한번도 안 찍은 레벨"에서 즉시 체결된 것처럼 되어버리는 팬텀 체결 버그가 됨
                    # (라이브는 거래소에 실제 지정가 스탑주문을 걸어두는 방식이라 이 문제가 없음 -
                    # 백테스트의 OHLC 근사 특유의 버그). 이번 캔들에 실제 도달한 가격을 못 넘도록 클램프.
                    if side == "long":
                        staged_sl = min(staged_sl, position["max_profit_price"])
                    else:
                        staged_sl = max(staged_sl, position["max_profit_price"])
                elif target_mode == "partial_lock":
                    locked_pct = peak_profit_pct * STAGE2_LOCK_RATIO
                    staged_sl = (position["entry"] * (1 + locked_pct / 100) if side == "long"
                                 else position["entry"] * (1 - locked_pct / 100))
                elif target_mode == "trailing":
                    giveback_pct = max(peak_profit_pct * STAGE3_TRAIL_RATIO, eff_s3_trail_min)
                    staged_sl = (position["max_profit_price"] * (1 - giveback_pct / 100) if side == "long"
                                 else position["max_profit_price"] * (1 + giveback_pct / 100))

                if staged_sl is not None:
                    if side == "long" and staged_sl > position["sl_price"]:
                        position["sl_price"] = staged_sl
                    elif side == "short" and staged_sl < position["sl_price"]:
                        position["sl_price"] = staged_sl

                if target_mode == "normal" and is_new_high:
                    bb = bollinger_at(candles, t)
                    w = bb["width"] if bb else position["entry_bb_width"]
                    if side == "long":
                        new_sl = position["max_profit_price"] - w * NORMAL_SL_MULT
                        if new_sl > position["sl_price"]:
                            position["sl_price"] = new_sl
                        new_tp = position["max_profit_price"] + w
                        if new_tp > position["tp_price"]:
                            position["tp_price"] = new_tp
                    else:
                        new_sl = position["max_profit_price"] + w * NORMAL_SL_MULT
                        if new_sl < position["sl_price"]:
                            position["sl_price"] = new_sl
                        new_tp = position["max_profit_price"] - w
                        if new_tp < position["tp_price"]:
                            position["tp_price"] = new_tp

                if target_mode == "normal":
                    if side == "long":
                        if price_low <= position["sl_price"] and price_high >= position["tp_price"]:
                            if sl_first:
                                sl_hit, exit_price, reason = True, position["sl_price"], "Stop Loss"
                            else:
                                tp_hit, exit_price, reason = True, position["tp_price"], "Take Profit"
                        elif price_low <= position["sl_price"]:
                            sl_hit, exit_price, reason = True, position["sl_price"], "Stop Loss"
                        elif price_high >= position["tp_price"]:
                            tp_hit, exit_price, reason = True, position["tp_price"], "Take Profit"
                    else:
                        if price_high >= position["sl_price"] and price_low <= position["tp_price"]:
                            if sl_first:
                                sl_hit, exit_price, reason = True, position["sl_price"], "Stop Loss"
                            else:
                                tp_hit, exit_price, reason = True, position["tp_price"], "Take Profit"
                        elif price_high >= position["sl_price"]:
                            sl_hit, exit_price, reason = True, position["sl_price"], "Stop Loss"
                        elif price_low <= position["tp_price"]:
                            tp_hit, exit_price, reason = True, position["tp_price"], "Take Profit"
                else:
                    stage_label = {"breakeven": "Breakeven", "partial_lock": "Partial Lock", "trailing": "Trailing"}
                    reason_label = f"{stage_label.get(target_mode, target_mode)} Stop"
                    if side == "long":
                        if price_low <= position["sl_price"]:
                            sl_hit, exit_price, reason = True, position["sl_price"], reason_label
                    else:
                        if price_high >= position["sl_price"]:
                            sl_hit, exit_price, reason = True, position["sl_price"], reason_label

            else:
                # ── 기존 단순화 로직 (normal/trailing 2단계, 참고용 - 라이브와 다름) ──
                close_profit_pct = (c["close"] - position["entry"]) / position["entry"] * 100
                if side == "short":
                    close_profit_pct = -close_profit_pct
                if position["mode"] == "normal" and close_profit_pct >= TRAILING_TRIGGER_PCT:
                    position["mode"] = "trailing"
                    position["trailing_ref"] = position["max_profit_price"]

                if position["mode"] == "trailing":
                    if side == "long":
                        if price_high > position["trailing_ref"]:
                            position["trailing_ref"] = price_high
                        trail_sl = position["trailing_ref"] * (1 - TRAILING_STOP_PCT / 100)
                        if price_low <= trail_sl:
                            sl_hit, exit_price, reason = True, trail_sl, "Trailing Stop"
                    else:
                        if price_low < position["trailing_ref"]:
                            position["trailing_ref"] = price_low
                        trail_sl = position["trailing_ref"] * (1 + TRAILING_STOP_PCT / 100)
                        if price_high >= trail_sl:
                            sl_hit, exit_price, reason = True, trail_sl, "Trailing Stop"
                else:  # normal
                    if side == "long":
                        if price_high > position["max_profit_price"]:
                            position["max_profit_price"] = price_high
                            bb = bollinger_at(candles, t)
                            w = bb["width"] if bb else position["entry_bb_width"]
                            new_sl = position["max_profit_price"] - w * NORMAL_SL_MULT
                            if new_sl > position["sl_price"]:
                                position["sl_price"] = new_sl
                            if tp_mode == "recede":
                                new_tp = position["max_profit_price"] + w
                                if new_tp > position["tp_price"]:
                                    position["tp_price"] = new_tp
                        if price_low <= position["sl_price"] and price_high >= position["tp_price"]:
                            if sl_first:
                                sl_hit, exit_price, reason = True, position["sl_price"], "Stop Loss"
                            else:
                                tp_hit, exit_price, reason = True, position["tp_price"], "Take Profit"
                        elif price_low <= position["sl_price"]:
                            sl_hit, exit_price, reason = True, position["sl_price"], "Stop Loss"
                        elif price_high >= position["tp_price"]:
                            tp_hit, exit_price, reason = True, position["tp_price"], "Take Profit"
                    else:  # short
                        if price_low < position["max_profit_price"]:
                            position["max_profit_price"] = price_low
                            bb = bollinger_at(candles, t)
                            w = bb["width"] if bb else position["entry_bb_width"]
                            new_sl = position["max_profit_price"] + w * NORMAL_SL_MULT
                            if new_sl < position["sl_price"]:
                                position["sl_price"] = new_sl
                            if tp_mode == "recede":
                                new_tp = position["max_profit_price"] - w
                                if new_tp < position["tp_price"]:
                                    position["tp_price"] = new_tp
                        if price_high >= position["sl_price"] and price_low <= position["tp_price"]:
                            if sl_first:
                                sl_hit, exit_price, reason = True, position["sl_price"], "Stop Loss"
                            else:
                                tp_hit, exit_price, reason = True, position["tp_price"], "Take Profit"
                        elif price_high >= position["sl_price"]:
                            sl_hit, exit_price, reason = True, position["sl_price"], "Stop Loss"
                        elif price_low <= position["tp_price"]:
                            tp_hit, exit_price, reason = True, position["tp_price"], "Take Profit"

            if sl_hit or tp_hit:
                pnl_pct = (exit_price - position["entry"]) / position["entry"]
                if side == "short":
                    pnl_pct = -pnl_pct
                nominal = seed * ENTRY_PERCENT * LEVERAGE
                gross = nominal * pnl_pct
                fees = nominal * FEE_RATE * 2
                net = gross - fees
                seed += net
                trades.append({
                    "side": side, "entry": position["entry"], "exit": exit_price,
                    "entry_ts": position["entry_ts"], "exit_ts": c["ts"],
                    "reason": reason, "profit": net, "profit_pct": pnl_pct * 100 * LEVERAGE
                })
                last_close_ts = c["ts"]
                position = None
                continue

        # ---- 신규 진입 체크 ----
        if not position:
            if last_close_ts is not None and (c["ts"] - last_close_ts) / 1000 < REENTRY_COOLDOWN_SEC:
                continue

            wi = width_info_at(candles, t)
            if wi is None:
                continue
            cw, aw = wi["current_width"], wi["avg_width"]

            def determine_signal():
                return "long" if wi["candle_close"] > wi["candle_open"] else (
                    "short" if wi["candle_close"] < wi["candle_open"] else None)

            def apply_filters(signal):
                if signal and use_adx_filter:
                    adx_info = adx_at(candles, t)
                    if adx_info is None:
                        signal = None
                    elif adx_info["adx"] < ADX_CHOP_THRESHOLD:
                        signal = None
                    else:
                        trend_ok = (
                            (signal == "long" and adx_info["plus_di"] > adx_info["minus_di"]) or
                            (signal == "short" and adx_info["minus_di"] > adx_info["plus_di"])
                        )
                        if not trend_ok:
                            signal = None

                if signal and use_hma_filter:
                    hma_info = hma_at(candles, t, period=hma_period)
                    if hma_info is None:
                        signal = None
                    else:
                        trend_ok = (
                            (signal == "long" and wi["candle_close"] > hma_info["hma"]) or
                            (signal == "short" and wi["candle_close"] < hma_info["hma"])
                        )
                        if not trend_ok:
                            signal = None

                if signal and htf_trend_fn is not None:
                    trend = htf_trend_fn(c["ts"])
                    if trend is None:
                        signal = None
                    else:
                        trend_ok = (
                            (signal == "long" and trend == "up") or
                            (signal == "short" and trend == "down")
                        )
                        if not trend_ok:
                            signal = None
                return signal

            def open_position(signal):
                entry_price = c["close"]
                if entry_sizing == "atr":
                    atr_res = atr_at(candles, t)
                    bb_width = (atr_res["atr"] * atr_mult) if atr_res else entry_price * 0.002
                else:
                    bb = bollinger_at(candles, t)
                    bb_width = bb["width"] if bb else entry_price * 0.002
                bb_width = max(bb_width, entry_price * 0.002)

                if live_staging:
                    # 라이브 진입 로직 재현: sl_distance = min(bb_width, entry*min(SL_PERCENT, (1/LEVERAGE)*0.8))
                    # TP는 상한 없이 항상 bb_width 그대로 (라이브와 동일)
                    leverage_safety_pct = (1 / LEVERAGE) * 0.8 if LEVERAGE > 0 else SL_PERCENT
                    max_sl_distance_pct = min(SL_PERCENT, leverage_safety_pct)
                    max_sl_distance = entry_price * max_sl_distance_pct
                    sl_distance = min(bb_width, max_sl_distance)

                    if signal == "long":
                        tp = entry_price + bb_width
                        sl = entry_price - sl_distance
                    else:
                        tp = entry_price - bb_width
                        sl = entry_price + sl_distance

                    return {
                        "side": signal, "entry": entry_price, "entry_ts": c["ts"],
                        "tp_price": tp, "sl_price": sl, "max_profit_price": entry_price,
                        "entry_bb_width": bb_width, "entry_bb_pct": bb_width / entry_price * 100,
                        "mode": "normal", "profit_mode": "normal"
                    }

                if signal == "long":
                    tp = entry_price + bb_width
                    sl = entry_price - bb_width
                else:
                    tp = entry_price - bb_width
                    sl = entry_price + bb_width

                return {
                    "side": signal, "entry": entry_price, "entry_ts": c["ts"],
                    "tp_price": tp, "sl_price": sl, "max_profit_price": entry_price,
                    "entry_bb_width": bb_width, "mode": "normal", "profit_mode": "normal"
                }

            if breakout_mode == "direct":
                # v9: 스퀴즈 전제조건 없이, cw가 aw*direct_mult를 "처음" 넘어서는
                # 그 캔들에만 진입 (엣지 트리거 - 넓게 유지되는 동안 재신호 방지)
                is_above = cw > aw * direct_mult
                fired = is_above and not direct_prev_above
                direct_prev_above = is_above

                if fired:
                    signal = apply_filters(determine_signal())
                    if signal:
                        position = open_position(signal)
            else:
                if squeeze_status == "normal":
                    if cw < aw * SQUEEZE_ENTER_MULT:
                        squeeze_status = "squeeze"
                        squeeze_width = cw
                        squeeze_avg_sum = cw
                        squeeze_avg_count = 1
                        squeeze_avg = cw
                elif squeeze_status == "squeeze":
                    if breakout_mode == "squeeze":
                        if cw < squeeze_width:
                            squeeze_width = cw
                        fired = cw > squeeze_width * squeeze_mult
                    elif breakout_mode == "squeeze_avg":
                        fired = cw > squeeze_avg * squeeze_mult
                    else:  # "avg" (구 로직)
                        fired = cw > aw

                    if fired:
                        signal = apply_filters(determine_signal())
                        squeeze_status = "normal"
                        if signal:
                            position = open_position(signal)
                    elif breakout_mode == "squeeze_avg":
                        # 발동 안 됐으면 이번 샘플을 평균에 반영
                        squeeze_avg_sum += cw
                        squeeze_avg_count += 1
                        squeeze_avg = squeeze_avg_sum / squeeze_avg_count

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

    # MDD (누적 seed 곡선 기준)
    curve = [SEED]
    s = SEED
    for t in trades:
        s += t["profit"]
        curve.append(s)
    peak = curve[0]
    mdd = 0
    for v in curve:
        peak = max(peak, v)
        dd = (peak - v) / peak * 100
        mdd = max(mdd, dd)

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

    configs = [
        # label, breakout_mode, tp_mode, use_adx, use_hma, direct_mult
        ("1) BASELINE (v1: 25시간 avg_width 진입 + TP recede 버그)", "avg", "recede", False, False, 1.5),
        ("2) v2 (스퀴즈 최저점 진입 + TP recede 버그)", "squeeze", "recede", False, False, 1.5),
        ("3) v2 + TP 고정 수정", "squeeze", "frozen", False, False, 1.5),
        ("4) v3 (스퀴즈 구간 평균 진입 + TP recede 버그)", "squeeze_avg", "recede", False, False, 1.5),
        ("5) v3 + TP 고정 (필터 없음, 즉시진입)", "squeeze_avg", "frozen", False, False, 1.5),
        ("6) v3 + TP 고정 + ADX(14)/DI 필터 (v8)", "squeeze_avg", "frozen", True, False, 1.5),
        ("7) v3 + TP 고정 + HMA200 필터 (종가 vs HMA200, 구 v7)", "squeeze_avg", "frozen", False, True, 1.5),
        ("8) v3 + TP 고정 + ADX/DI + HMA200 둘 다", "squeeze_avg", "frozen", True, True, 1.5),
        # v9: 스퀴즈 전제조건 없이 cw > aw*mult 직접 트리거 (엣지), ADX/DI 필터 포함
        ("9a) DIRECT mult=1.2 + ADX/DI", "direct", "frozen", True, False, 1.2),
        ("9b) DIRECT mult=1.5 + ADX/DI", "direct", "frozen", True, False, 1.5),
        ("9c) DIRECT mult=2.0 + ADX/DI", "direct", "frozen", True, False, 2.0),
        ("9d) DIRECT mult=2.5 + ADX/DI", "direct", "frozen", True, False, 2.5),
        ("9e) DIRECT mult=1.5, 필터 없음", "direct", "frozen", False, False, 1.5),
    ]

    for label, bmode, tmode, use_adx, use_hma, dmult in configs:
        trades, final_seed = run_backtest(candles, breakout_mode=bmode, tp_mode=tmode, sl_first=True,
                                           use_adx_filter=use_adx, use_hma_filter=use_hma, direct_mult=dmult)
        summarize(label + " [sl_first]", trades, final_seed)
