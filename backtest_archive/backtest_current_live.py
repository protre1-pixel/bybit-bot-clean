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


def compute_width_series(candles, lookback=WIDTH_LOOKBACK):
    """width_info_at()의 current_width를 전 구간에 대해 한번에 벡터화 계산.
    width_info_at은 매 t마다 최근 fetch_window(100)개만 잘라서 재계산하지만, 실제로
    각 시점의 current_width는 그 시점 기준 최근 lookback(30)개 종가에만 의존하므로
    (fetch_window는 avg_width 계산용 여유분일 뿐) 결과값은 전체 시계열에 대해
    pandas rolling으로 한 번에 계산한 것과 완전히 동일함(단, ddof=0으로 모집단 표준편차
    사용 - width_info_at의 np.std 기본값과 일치). 30개 전봉 최솟값 비교처럼 과거
    lookback개 폭이 반복적으로 필요한 경우, t마다 width_info_at을 30번씩 호출하면
    느리므로(각 호출이 자체적으로 ~70개 rolling stat을 다시 계산) 이 벡터화 버전을
    미리 한 번 계산해두고 배열 인덱싱만 하기 위한 용도."""
    close = pd.Series([c["close"] for c in candles])
    sma = close.rolling(lookback).mean()
    std = close.rolling(lookback).std(ddof=0)
    width = (sma + 2 * std) - (sma - 2 * std)
    return width.to_numpy()


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


def hma_slope_at(candles, t, period=HMA_GAP_FAST, lookback=5):
    """2026-08-14 실험: HMA200(HMA_GAP_FAST)의 기울기 방향 측정.
    사용자가 BTC 차트에서 관찰한 "HMA200/600은 정배열(상승장 판정)인데 정작 HMA200
    자체는 이미 꺾여서 하락 중"인 후행지표 문제를 잡기 위함. htf_trend_at()은 HMA200 vs
    HMA600의 순서(부호)만 보므로 이 문제를 못 잡음 - 별도로 HMA200 자체의 최근 lookback개
    캔들간 변화량(기울기)을 계산해서 방향을 반환. 데이터 부족하면 None."""
    cur = hma_at(candles, t, period)
    prev = hma_at(candles, t - lookback, period)
    if cur is None or prev is None:
        return None
    slope = cur["hma"] - prev["hma"]
    if slope > 0:
        return "up"
    elif slope < 0:
        return "down"
    return None


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
                  use_price_alignment_filter=False, use_hma_direction_only=False, hma_gap_min_pct=0.0,
                  require_hma_slope=False, hma_slope_lookback=5, use_regime_exit=False,
                  use_fast_breakout=False, fast_breakout_lookback=2, fast_breakout_mult=None,
                  use_price_vs_hma200_direction=False,
                  use_2candle_breakout=False, two_candle_breakout_mult=2.5,
                  use_min_width_breakout=False, min_width_lookback=30, min_width_mult=2.0,
                  entry_sl_cap_pct=None,
                  stall_exit_candles=None, stall_exit_min_peak_pct=0.15, stall_exit_sl_pct=0.8):
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
    같은 봉에서 SL도 동시에 닿으면 보수적으로 SL을 우선. None이면 비활성(기존과 동일).

    use_hma_direction_only: 2026-08-14 실험 - 기존엔 브레이크아웃 캔들의 몸통(양봉/음봉)으로
    방향을 먼저 정하고, 그 방향이 HMA200/600 정배열과 반대면 진입을 취소했음(예: 양봉인데
    역배열이면 취소). 이 옵션은 캔들 방향을 아예 안 보고, 브레이크아웃이 뜬 순간의 HMA200/600
    정배열 상태로 방향을 바로 결정(up→롱, down→숏). 캔들-HMA 불일치로 인한 "취소, 재대기"가
    구조적으로 없어짐(HMA 계산 불가로 인한 취소만 남음). use_hma_regime_filter/
    use_price_alignment_filter와는 배타적으로 사용(방향 자체를 HMA가 정하므로 별도 필터 불필요).

    hma_gap_min_pct: 2026-08-14 실험 - use_hma_direction_only가 단순히 HMA200 vs HMA600
    부호(+/-)만 보고 방향을 정해서, 두 선이 거의 붙어있는(추세가 약한/막 뒤집힌) 구간에서도
    진입을 허용하는 노이즈 문제 보완용. |HMA200-HMA600| / 현재가 × 100 (%)이 이 값 미만이면
    "추세가 아직 약하다"고 보고 진입 취소. use_hma_direction_only=True일 때만 적용, 0이면
    비활성(기존과 동일, 부호만 확인).

    require_hma_slope/hma_slope_lookback: 2026-08-14 실험 - 사용자가 BTC 차트에서 관찰한
    "HMA200/600 정배열(regime='up')인데 HMA200 자체는 이미 꺾여서 내려가는 중" 케이스를
    잡기 위한 추가 확인. use_hma_regime_filter 분기에서 기존 regime(부호) 확인을 통과해도,
    HMA200의 최근 hma_slope_lookback개 캔들간 기울기 방향이 신호 방향과 다르면(롱인데
    slope가 down, 또는 숏인데 slope가 up) 진입 취소. False면 비활성(기존과 동일).

    use_regime_exit: 2026-08-14 실험 - 진입필터(HMA200 vs HMA600 정배열)와 0단계(normal)
    청산 하드룰(현재가 vs HMA200 단일선)이 서로 다른 기준을 써서, 진입 시점에 가격이 이미
    HMA200 반대쪽인 눌림목 진입이 진입 직후(15분/1캔들)만에 즉시 손절되는 문제 확인 후,
    청산 기준도 진입필터와 동일하게 "HMA200 vs HMA600 정배열"로 맞추면 어떻게 되는지
    검증용. True면 0단계에서 가격 위치 대신 regime이 불리하게 뒤집히는 순간(해당 캔들
    종가 기준) 청산. False면 기존과 동일(가격 vs HMA200 단일선, 인트라바 저가/고가 기준).

    use_fast_breakout/fast_breakout_lookback/fast_breakout_mult: 2026-08-15 실험 - 기존 로직은
    반드시 "스퀴즈(폭이 평균 대비 SQUEEZE_ENTER_MULT 이하로 눌린 상태)"가 먼저 감지돼야만
    그 이후의 확장을 breakout으로 인정함. 그래서 스퀴즈 선행 없이 갑자기 튀는 진짜 큰
    브레이크아웃은 아예 후보로도 안 잡히고, 그 뒤 가격이 잠깐 눌리며 새로 스퀴즈가 형성된
    다음의 작은 재확장에서야(이미 저점/고점 근처) 뒤늦게 추격 진입하는 문제가 사용자 관찰로
    확인됨(SOL 차트: 큰 급락 캔들은 놓치고 그 이후 반등 직전 저점에서 숏 진입). 이 옵션은
    squeeze_status=="normal"이고 스퀴즈 진입 조건도 아닐 때, 폭이 fast_breakout_lookback개
    캔들 전 폭 대비 fast_breakout_mult배 이상 급확장되면 스퀴즈 선행 여부와 무관하게 즉시
    breakout 후보로 인정(신호판정/필터는 기존 breakout 경로와 동일하게 재사용). fast_breakout_mult
    None이면 BREAKOUT_MULT 재사용. False면 비활성(기존과 동일).

    use_price_vs_hma200_direction: 2026-08-15 실험 - 사용자가 기억하는 "정배열/역배열 필터
    추가하기 전, 200일선(HMA200)만 보고 캔들이 그 위면 롱/아래면 숏이었던" 원래 방식을 재현.
    기존엔 breakout 캔들의 몸통(양봉/음봉)으로 방향을 먼저 정했는데, 이 옵션은 캔들 방향을
    아예 무시하고 breakout 캔들 종가가 HMA200(HMA_ENTRY_PERIOD) 위/아래인지로 바로 방향을
    정함(use_hma_direction_only와 구조는 같으나, 기준이 "HMA200/600 정배열 부호"가 아니라
    "가격 vs HMA200 단일선 위치"라는 점이 다름). use_hma_direction_only와 배타적. 이후
    use_hma_regime_filter 등 기존 필터 체인은 그대로 적용됨(둘 다 True면 "가격 vs HMA200으로
    방향 결정 + HMA200/600 정배열로 재확인" 조합). False면 비활성(기존과 동일, 캔들 몸통 기준).

    use_2candle_breakout/two_candle_breakout_mult: 2026-08-16 실험 - 사용자가 기존 스퀴즈
    선행조건부 state machine(normal→squeeze→breakout) 자체를 문제로 지목(스퀴즈 없이
    바로 터지는 진짜 브레이크아웃을 놓치고, 죽은 횡보장에서는 squeeze_min이 계속
    수축하며 상대비율 조건이라 사소한 노이즈에도 거짓 진입). 이 옵션은 state machine을
    완전히 대체(fast_breakout처럼 normal 상태에서만 보조로 붙는 게 아니라 항상 우선 적용):
    매 "완성된" 캔들 t마다 width_info_at(candles, t)(현재 폭, t시점 종가 기준)와
    width_info_at(candles, t-1)(직전 폭)만 비교해서, 현재 폭이 직전 폭의
    two_candle_breakout_mult배 이상이면 스퀴즈 상태와 무관하게 즉시 breakout 인정.
    squeeze_status는 계산은 하되(다른 옵션과의 호환을 위해 상태변수 자체는 유지) 이 옵션이
    True인 동안은 breakout 판정에 전혀 관여하지 않음. 방향판정(use_hma_direction_only 등)과
    청산로직은 완전히 그대로 유지 - 진입 타이밍만 교체하는 1차 실험. False면 비활성(기존과 동일).

    use_min_width_breakout/min_width_lookback/min_width_mult: 2026-08-16 실험 - 2candle_breakout을
    2.5배로 테스트해보니 1년에 2건만 뜸(원인: current_width가 30기간 롤링 SMA±2std라 한 봉
    사이에 값이 거의 안 움직여서, 직전 봉 대비 배율 조건 자체가 거의 항상 실패). 사용자가
    "전봉 1개가 아니라 최근 30개 전봉 중 가장 작았던 폭"을 기준으로 잡자고 제안 - 이러면
    구 state machine의 squeeze_min(스퀴즈 진입 이후로만 갱신되는 래칫)과 달리, 매 시점 롤링
    윈도우 최솟값이라 죽은 횡보장이 오래 지속돼도 계속 갱신되고, 스퀴즈 선행조건도 없음.
    매 완성된 캔들 t마다: 직전 min_width_lookback(30)개 캔들(t-lookback..t-1)의
    current_width 중 최솟값을 구해서, 지금 캔들의 current_width가 그 최솟값의
    min_width_mult(2.0)배 이상이면 breakout 인정. compute_width_series()로 전체 구간을
    미리 벡터화 계산해두고(width_info_at을 30번씩 반복호출하면 느려서) 인덱싱만 함.
    use_2candle_breakout과 배타적(둘 다 True면 이 옵션이 우선). False면 비활성(기존과 동일).

    entry_sl_cap_pct/stall_exit_*: 2026-08-16 실험 - "가격정렬 필터"(use_price_alignment_filter)
    적용 후 Trend Follow Stop 172건을 까본 결과: peak가 profit_lock 트리거(0.5%)를 못 찍고
    반전된 60건이 진입시점의 "원래 넓은 SL"(밴드폭 또는 최대 SL_PERCENT=3.5% 중 작은 쪽)을
    그대로 맞고 나가며 그룹 총손익 -$3,480(25/60 손실)을 만든 반면, 0.5%를 찍어서 profit_lock이
    걸린 112건은 전승(0손실, +$6,914)이었음. 즉 손실의 핵심은 "SL이 안 올라가서"가 아니라
    "트리거 전 SL이 너무 넓어서". 사용자가 제안한 3종 세트:
      1) profit_lock_trigger_pct를 낮춰서(테스트 스크립트에서 0.5→더 낮은 값으로 전달) 더
         일찍 보호 시작 - 기존 파라미터 재사용, 코드 변경 없음.
      2) stall_exit_candles/stall_exit_min_peak_pct/stall_exit_sl_pct: "초반 무동력" 조기청산.
         진입 후 stall_exit_candles개 캔들이 지나도록 peak_profit_pct가
         stall_exit_min_peak_pct%도 못 찍었으면, SL을 entry ∓ stall_exit_sl_pct%로 강제로
         좁힘(기존 SL/트레일링 SL과 비교해 "더 타이트한 쪽으로만" 적용 - 완화는 안 함). 단계
         (normal/trend_follow) 무관하게 항상 체크. None이면 비활성(기존과 동일).
      3) entry_sl_cap_pct: 진입 시점 SL 상한을 SL_PERCENT(3.5%) 대신 이 값(%)으로 교체.
         밴드폭이 넓은 변동성 구간에서 진입 SL 자체가 과도하게 넓게 열리는 것을 방지.
         None이면 기존(SL_PERCENT=3.5%) 그대로."""
    seed = SEED
    position = None
    trades = []
    squeeze_status = "normal"
    squeeze_width = None
    last_close_ts = None

    width_series = compute_width_series(candles) if use_min_width_breakout else None

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

            # 2026-08-16: "초반 무동력" 조기청산 - 진입 후 stall_exit_candles개 캔들이
            # 지나도록 peak_profit_pct가 stall_exit_min_peak_pct%도 못 찍었으면, SL을
            # entry ∓ stall_exit_sl_pct%로 강제로 좁힘(기존 SL보다 타이트할 때만 적용 -
            # 완화는 안 함). 단계(normal/trend_follow) 무관하게 항상 체크. profit_lock
            # 트리거 전까지 SL이 너무 넓게 열려있어서 생기던 손실(그룹 A, -$3,480/60건)을
            # 줄이기 위함.
            if stall_exit_candles is not None:
                candles_since_entry = t - position["entry_t"]
                if candles_since_entry >= stall_exit_candles and peak_profit_pct < stall_exit_min_peak_pct:
                    stall_sl = (entry * (1 - stall_exit_sl_pct / 100) if side == "long"
                                else entry * (1 + stall_exit_sl_pct / 100))
                    if side == "long" and stall_sl > position["sl_price"]:
                        position["sl_price"] = stall_sl
                    elif side == "short" and stall_sl < position["sl_price"]:
                        position["sl_price"] = stall_sl

            # 0단계(normal): 1h HMA200 반대쪽 이탈 시 즉시 청산 (+ 완충 버퍼)
            if position["profit_mode"] == "normal":
                if use_regime_exit:
                    # 2026-08-14 실험: 가격 vs HMA200 대신, 진입필터와 동일하게 HMA200 vs
                    # HMA600 정배열이 불리하게 뒤집리는 순간(캔들 종가 기준) 청산. 인트라바
                    # 저가/고가가 아니라 해당 캔들 종가로 판정(regime 자체가 종가 기반 계산).
                    regime_now = htf_trend_at(candles, t)
                    broke_regime = (
                        (side == "long" and regime_now == "down") or
                        (side == "short" and regime_now == "up")
                    )
                    if broke_regime:
                        exit_price, reason = close, "HMA200 Break"
                else:
                    h200 = hma_at(candles, t, HMA_ENTRY_PERIOD)
                    hma200_now = h200["hma"] if h200 else None
                    if hma200_now is not None:
                        # 2026-08-16 버그수정: 청산 체결가를 "HMA200 라인 값"이 아니라 실제
                        # 캔들 종가(close)로 사용. 라이브는 현재가(폴링) 대비 이탈을 감지해서
                        # 그 현재가로 즉시 청산(close_trade(coin_key, current_price, ...))하는데,
                        # 기존 백테스트는 체결가를 break_level(라인 값)로 잡아서 - 진입시점부터
                        # 이미 라인 반대쪽(눌림목)이었던 포지션은 실제 가격 움직임과 무관하게
                        # "라인값 vs 진입가" 차이만큼 항상 가짜 이익이 찍히는 구조였음(검증:
                        # HMA200 Break 261건 중 219건이 눌림목 진입이었고 그 219건의 승률이
                        # 97.7%였는데, 실제 라이브에서는 같은 유형 거래가 9/9 전부 손실).
                        if side == "long":
                            break_level = hma200_now * (1 - hma200_buffer_pct / 100)
                            if low < break_level:
                                exit_price, reason = close, "HMA200 Break"
                        else:
                            break_level = hma200_now * (1 + hma200_buffer_pct / 100)
                            if high > break_level:
                                exit_price, reason = close, "HMA200 Break"

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

        breakout_now = False

        if use_min_width_breakout:
            # 2026-08-16: 직전 봉 1개가 아니라, 최근 min_width_lookback(30)개 완성봉의
            # current_width 중 최솟값 대비 배율로 판정. 죽은 횡보장이 길어져도 계속
            # 갱신되는 롤링 최솟값이라 구 squeeze_min 래칫보다 노이즈에 덜 취약함.
            if t >= min_width_lookback:
                window_w = width_series[t - min_width_lookback:t]
                window_w = window_w[~np.isnan(window_w)]
                if len(window_w) > 0:
                    min_w = float(window_w.min())
                    if min_w > 0 and current_width >= min_w * min_width_mult:
                        breakout_now = True
        elif use_2candle_breakout:
            # 2026-08-16: 스퀴즈 선행조건 없이, 직전 완성봉 폭 대비 현재봉 폭의 절대 배율만
            # 본다. state machine(정상/스퀴즈)은 아예 관여하지 않음.
            wi_prev = width_info_at(candles, t - 1)
            if wi_prev is not None and wi_prev["current_width"] > 0:
                if current_width >= wi_prev["current_width"] * two_candle_breakout_mult:
                    breakout_now = True
        elif squeeze_status == "normal":
            if current_width < avg_width * SQUEEZE_ENTER_MULT:
                squeeze_status = "squeeze"
                squeeze_width = current_width
            elif use_fast_breakout:
                wi_back = width_info_at(candles, t - fast_breakout_lookback)
                if wi_back is not None and wi_back["current_width"] > 0:
                    fb_mult = fast_breakout_mult if fast_breakout_mult is not None else BREAKOUT_MULT
                    if current_width > wi_back["current_width"] * fb_mult:
                        breakout_now = True
        elif squeeze_status == "squeeze":
            if current_width < squeeze_width:
                squeeze_width = current_width

            if current_width > squeeze_width * BREAKOUT_MULT:
                squeeze_status = "normal"
                breakout_now = True

        if breakout_now:
                if use_hma_direction_only:
                    # 2026-08-14: 캔들 몸통(양봉/음봉) 무시, 브레이크아웃 시점 HMA200/600
                    # 정배열/역배열로 바로 방향 결정. 불일치로 인한 취소 자체가 없어짐.
                    regime = htf_trend_at(candles, t)
                    if regime == "up":
                        signal = "long"
                    elif regime == "down":
                        signal = "short"
                    else:
                        signal = None

                    if signal and hma_gap_min_pct > 0:
                        gap_info = hma_gap_at(candles, t)
                        if gap_info is None:
                            signal = None
                        else:
                            gap_pct = abs(gap_info["gap"]) / candle_close * 100
                            if gap_pct < hma_gap_min_pct:
                                signal = None
                elif use_price_vs_hma200_direction:
                    # 2026-08-15: 캔들 몸통(양봉/음봉) 무시, breakout 캔들 종가가 HMA200
                    # 위/아래인지로 바로 방향 결정 (정배열/역배열 필터 도입 전 원래 방식 재현).
                    h200_dir = hma_at(candles, t, HMA_ENTRY_PERIOD)
                    hma200_dir_now = h200_dir["hma"] if h200_dir else None
                    if hma200_dir_now is None:
                        signal = None
                    elif candle_close > hma200_dir_now:
                        signal = "long"
                    elif candle_close < hma200_dir_now:
                        signal = "short"
                    else:
                        signal = None
                else:
                    signal = None
                    if candle_close > candle_open:
                        signal = "long"
                    elif candle_close < candle_open:
                        signal = "short"

                if signal and volume_mult is not None:
                    vc = volume_confirmed_at(candles, t, mult=volume_mult)
                    if not vc:
                        signal = None

                if signal and adx_min is not None:
                    adx_val = adx_at(candles, t)
                    if adx_val is None or adx_val < adx_min:
                        signal = None

                if signal and use_hma_direction_only:
                    if use_price_alignment_filter:
                        # 2026-08-16: 방향은 그대로 regime(200/600 정배열 부호)로 정하되,
                        # "가격이 이미 그 방향으로 완전히 정배열된 상태"(눌림목 아님)일 때만
                        # 진입 허용. 롱: 가격>200>600, 숏: 가격<200<600. 이러면 진입 시점부터
                        # 가격이 HMA200 반대쪽에 있는(=0단계 HMA200 하드이탈룰에 바로 걸리는)
                        # "눌림목 진입" 자체가 원천 차단됨 - 진입 직후 15분만에 즉시청산되던
                        # 문제의 근본 원인을 진입단에서 제거하는 실험.
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
                elif signal:
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
                        # 2026-08-14: 여긴 실전(trading_service.py apply_entry_filters)과 동일한
                        # "캔들방향 우선 + HMA정배열 확인" 로직. hma_gap_min_pct 갭크기 필터를 여기에도
                        # 연결(기존엔 use_hma_direction_only 분기에만 있었음) - 실전 로직 그대로 유지한
                        # 채 갭임계값 효과만 검증하기 위함. 0이면 기존과 동일(부호만 확인).
                        regime = htf_trend_at(candles, t)
                        trend_ok = (signal == "long" and regime == "up") or (signal == "short" and regime == "down")
                        if not trend_ok:
                            signal = None
                        elif hma_gap_min_pct > 0:
                            gap_info = hma_gap_at(candles, t)
                            if gap_info is None:
                                signal = None
                            else:
                                gap_pct = abs(gap_info["gap"]) / candle_close * 100
                                if gap_pct < hma_gap_min_pct:
                                    signal = None
                        if signal and require_hma_slope:
                            slope_dir = hma_slope_at(candles, t, HMA_GAP_FAST, hma_slope_lookback)
                            slope_ok = (signal == "long" and slope_dir == "up") or (signal == "short" and slope_dir == "down")
                            if not slope_ok:
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
                    sl_cap = (entry_sl_cap_pct / 100) if entry_sl_cap_pct is not None else SL_PERCENT
                    max_sl_distance_pct = min(sl_cap, leverage_safety_pct)
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
                        "side": signal, "entry": entry_price, "entry_ts": ts, "entry_t": t,
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
