"""가격 조회 및 기술적 분석"""
import os
import time
import logging
import threading
import yfinance as yf
import pandas as pd
import numpy as np
from app import config
from app.utils import (
    load_state,
    save_state,
    state_transaction,
    load_trades,
    save_trades,
    format_price
)
from .trading_service import auto_trade, close_trade

logger = logging.getLogger(__name__)


def get_current_price(symbol):
    """Bybit에서 현재 가격 조회 - 현물 마진 거래"""
    try:
        if config.bybit_client:
            # 심볼 정규화 (BTC-USD -> BTC)
            coin = symbol.split('-')[0] if '-' in symbol else symbol
            coin = coin.upper()

            # BTC, ETH 등을 BTCUSDT, ETHUSDT로 변환
            if coin == "BTC":
                pair = "BTCUSDT"
            elif coin == "ETH":
                pair = "ETHUSDT"
            else:
                pair = f"{coin}USDT"

            # Futures 마켓에서 가격 조회
            response = config.bybit_client.get_tickers(category="linear", symbol=pair)

            if response['retCode'] == 0 and response['result']['list']:
                price = float(response['result']['list'][0]['lastPrice'])
                return format_price(price, coin)
            else:
                logger.error(f"[ERROR] Bybit API 응답 오류 ({pair}): {response}")
        else:
            # Bybit 연결 실패시 yfinance 폴백
            ticker = yf.Ticker(symbol if "-" in symbol else f"{symbol}-USD")
            data = ticker.history(period='1d')
            if len(data) > 0:
                price = float(data['Close'].iloc[-1])
                return format_price(price, symbol.split('-')[0] if '-' in symbol else symbol)
    except Exception as e:
        logger.error(f"[ERROR] get_current_price ({symbol}): {e}")
    return None


def calculate_atr(symbol, period=14, timeframe=60):
    """Bybit에서 ATR 계산 (전봉 기준)"""
    try:
        # 심볼 변환 (BTC -> BTCUSDT)
        if symbol == "BTC":
            pair = "BTCUSDT"
        elif symbol == "ETH":
            pair = "ETHUSDT"
        else:
            pair = f"{symbol.upper()}USDT"

        # timeframe을 분에서 Bybit interval로 변환
        if timeframe < 60:
            interval = str(timeframe)  # "5", "15", "30"
        elif timeframe == 60:
            interval = "60"  # 1시간
        elif timeframe == 240:
            interval = "240"  # 4시간
        elif timeframe == 1440:
            interval = "1d"  # 일봉
        else:
            interval = "60"

        # Bybit에서 OHLCV 데이터 조회 (현물 마진)
        if config.bybit_client:
            response = config.bybit_client.get_kline(
                category="linear",
                symbol=pair,
                interval=interval,
                limit=200  # 최대 200개
            )

            if response['retCode'] != 0 or not response['result']['list']:
                return None

            # Bybit 데이터 형식: [timestamp, open, high, low, close, volume, ...]
            data_list = response['result']['list']

            # 역순으로 정렬 (최신이 끝에)
            data_list.reverse()

            if len(data_list) < period + 1:
                return None

            high = np.array([float(x[2]) for x in data_list], dtype=float)
            low = np.array([float(x[3]) for x in data_list], dtype=float)
            close = np.array([float(x[4]) for x in data_list], dtype=float)

            tr1 = high - low
            tr2 = np.abs(high - np.roll(close, 1))
            tr3 = np.abs(low - np.roll(close, 1))

            tr = np.maximum(tr1, np.maximum(tr2, tr3))
            atr_values = pd.Series(tr).rolling(window=period).mean().values
            atr = float(atr_values[-2]) if len(atr_values) > 1 and not pd.isna(atr_values[-2]) else None

            return atr
        else:
            logger.warning(f"[WARN] Bybit 연결 실패, yfinance 폴백: {symbol}")
            data = yf.download(f"{symbol}-USD", period='60d', interval='1h', progress=False)
            if data is None or len(data) < period + 1:
                return None

            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.droplevel(1)

            high = np.asarray(data['High']).flatten()
            low = np.asarray(data['Low']).flatten()
            close = np.asarray(data['Close']).flatten()

            tr1 = high - low
            tr2 = np.abs(high - np.roll(close, 1))
            tr3 = np.abs(low - np.roll(close, 1))

            tr = np.maximum(tr1, np.maximum(tr2, tr3))
            atr_values = pd.Series(tr).rolling(window=period).mean().values
            atr = float(atr_values[-2]) if len(atr_values) > 1 and not pd.isna(atr_values[-2]) else None

            return atr
    except Exception as e:
        logger.error(f"[ERROR] ATR 계산 에러: {symbol} - {e}")
        return None


def calculate_sma(symbol, period=20, timeframe=60):
    """Bybit에서 SMA 계산 (전봉 기준)"""
    try:
        # 심볼 변환 (BTC -> BTCUSDT)
        if symbol == "BTC":
            pair = "BTCUSDT"
        elif symbol == "ETH":
            pair = "ETHUSDT"
        else:
            pair = f"{symbol.upper()}USDT"

        # timeframe을 분에서 Bybit interval로 변환
        if timeframe < 60:
            interval = str(timeframe)
        elif timeframe == 60:
            interval = "60"
        elif timeframe == 240:
            interval = "240"
        elif timeframe == 1440:
            interval = "1d"
        else:
            interval = "60"

        # Bybit에서 OHLCV 데이터 조회
        if config.bybit_client:
            response = config.bybit_client.get_kline(
                category="linear",
                symbol=pair,
                interval=interval,
                limit=200
            )

            if response['retCode'] != 0 or not response['result']['list']:
                return None

            data_list = response['result']['list']
            data_list.reverse()

            if len(data_list) < period + 1:
                return None

            close = np.array([float(x[4]) for x in data_list], dtype=float)
            sma_values = pd.Series(close).rolling(window=period).mean().values
            sma = float(sma_values[-2]) if len(sma_values) > 1 and not pd.isna(sma_values[-2]) else None

            return sma
        else:
            # Bybit 연결 실패시 yfinance 폴백
            data = yf.download(f"{symbol}-USD", period='60d', interval='1h', progress=False)
            if data is None or len(data) < period + 1:
                return None

            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.droplevel(1)

            close = np.asarray(data['Close']).flatten()
            sma_values = pd.Series(close).rolling(window=period).mean().values
            sma = float(sma_values[-2]) if len(sma_values) > 1 and not pd.isna(sma_values[-2]) else None

            return sma
    except Exception as e:
        logger.error(f"[ERROR] SMA 계산 에러: {symbol} - {e}")
        return None


def calculate_wma(closes, period):
    """가중이동평균 (WMA) 계산"""
    weights = np.arange(1, period + 1)
    wma = pd.Series(closes).rolling(window=period).apply(
        lambda x: np.sum(weights * x) / np.sum(weights), raw=False
    ).values
    return wma


def calculate_hma(symbol, period=60, timeframe=60):
    """Bybit에서 HMA(Hull Moving Average) 계산 (전봉 기준)"""
    try:
        # 심볼 변환 (BTC -> BTCUSDT)
        if symbol == "BTC":
            pair = "BTCUSDT"
        elif symbol == "ETH":
            pair = "ETHUSDT"
        else:
            pair = f"{symbol.upper()}USDT"

        # timeframe을 분에서 Bybit interval로 변환
        if timeframe < 60:
            interval = str(timeframe)
        elif timeframe == 60:
            interval = "60"
        elif timeframe == 240:
            interval = "240"
        elif timeframe == 1440:
            interval = "1d"
        else:
            interval = "60"

        # Bybit에서 OHLCV 데이터 조회
        if config.bybit_client:
            response = config.bybit_client.get_kline(
                category="linear",
                symbol=pair,
                interval=interval,
                limit=max(period + 100, 200)
            )

            if response['retCode'] != 0 or not response['result']['list']:
                return None

            data_list = response['result']['list']
            data_list.reverse()

            if len(data_list) < period + 50:
                return None

            close = np.array([float(x[4]) for x in data_list], dtype=float)

            # HMA 계산
            half_period = int(period / 2)
            sqrt_period = int(np.sqrt(period))

            wma1 = calculate_wma(close, half_period)
            wma2 = calculate_wma(close, period)

            diff = 2 * wma1 - wma2
            hma_values = calculate_wma(diff, sqrt_period)
            hma = float(hma_values[-2]) if len(hma_values) > 1 and not pd.isna(hma_values[-2]) else None

            # HMA 값이 유효한지 확인
            if hma is not None and not np.isnan(hma):
                return hma
            return None
        else:
            logger.warning(f"[WARN] Bybit 연결 실패, HMA 계산 불가: {symbol}")
            return None
    except Exception as e:
        logger.error(f"[ERROR] HMA 계산 에러: {symbol} - {e}")
        return None


def get_htf_trend(symbol, fast_period=200, slow_period=600, timeframe=60):
    """상위 타임프레임(기본 1시간봉) HMA200/HMA600 정배열/역배열 추세 필터.
    2026-08-07: 백테스트에서 확인된 최선 조합(squeeze 최저점기준 진입 + ADX + 1h HTF
    HMA200/600 정배열)을 라이브에 반영하면서 추가. HMA200 > HMA600이면 "up"(상승 추세),
    HMA200 < HMA600이면 "down"(하락 추세), 계산 불가/횡보(같은 값)면 None.
    calculate_hma() 재사용 - period=600일 때 klines를 넉넉히(700개) 불러오므로 API 부담이
    있어 호출부(trading_service)에서 캐싱해서 씀(매 breakout마다 새로 부르지 않음)."""
    hma_fast = calculate_hma(symbol, period=fast_period, timeframe=timeframe)
    hma_slow = calculate_hma(symbol, period=slow_period, timeframe=timeframe)
    if hma_fast is None or hma_slow is None:
        return None
    if hma_fast > hma_slow:
        return "up"
    elif hma_fast < hma_slow:
        return "down"
    return None


def get_hma_gap(symbol, fast_period=60, slow_period=180, timeframe=15):
    """HMA(빠른)-HMA(느린) 갭(부호 있는 값) 계산. 2026-08-07: 청산(추세추종) 단계에서
    "추세가 살아있는 동안 계속 들고, 갭이 진입 이후 최댓값 대비 줄어들면 정리"하는 로직에
    사용. 1h HTF 필터(get_htf_trend, 200/600)는 진입 게이트용이고, 이건 15분봉 기준
    60/180으로 더 빠르게 반응하도록 별도로 둠(트레이드 하나의 수명에 맞춘 lookback)."""
    hma_fast = calculate_hma(symbol, period=fast_period, timeframe=timeframe)
    hma_slow = calculate_hma(symbol, period=slow_period, timeframe=timeframe)
    if hma_fast is None or hma_slow is None:
        return None
    return {"gap": hma_fast - hma_slow, "fast": hma_fast, "slow": hma_slow}


def calculate_adx(symbol, period=14, timeframe=15):
    """ADX/+DI/-DI 계산 (Wilder 평활). 2026-08-07: 스퀴즈 브레이크아웃 방향이
    진짜 추세인지(휩소성 도지/횡보가 아닌지) 확인하는 필터용으로 추가.
    백테스트(backtest_bb_squeeze.py의 adx_at)와 동일 로직 - 마지막으로 "완성된"
    캔들(index -2) 기준."""
    try:
        if not config.bybit_client:
            return None
        if symbol == "BTC":
            pair = "BTCUSDT"
        elif symbol == "ETH":
            pair = "ETHUSDT"
        else:
            pair = f"{symbol.upper()}USDT"

        interval = str(timeframe) if timeframe < 60 else ("60" if timeframe == 60 else str(timeframe))

        response = config.bybit_client.get_kline(
            category="linear",
            symbol=pair,
            interval=interval,
            limit=max(period * 4 + 50, 200)
        )

        if response['retCode'] != 0 or not response['result']['list']:
            return None

        data_list = response['result']['list']
        data_list.reverse()

        if len(data_list) < period * 3 + 5:
            return None

        high = np.array([float(x[2]) for x in data_list], dtype=float)
        low = np.array([float(x[3]) for x in data_list], dtype=float)
        close = np.array([float(x[4]) for x in data_list], dtype=float)

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

    except Exception as e:
        logger.error(f"[ERROR] ADX 계산 에러: {symbol} - {e}")
        return None


def calculate_rsi(symbol, period=14, timeframe=60):
    """Bybit에서 RSI 계산"""
    try:
        # 심볼 변환
        if symbol == "BTC":
            pair = "BTCUSDT"
        elif symbol == "ETH":
            pair = "ETHUSDT"
        else:
            pair = f"{symbol.upper()}USDT"

        # timeframe 변환
        if timeframe < 60:
            interval = str(timeframe)
        elif timeframe == 60:
            interval = "60"
        elif timeframe == 240:
            interval = "240"
        elif timeframe == 1440:
            interval = "1d"
        else:
            interval = "60"

        if config.bybit_client:
            response = config.bybit_client.get_kline(
                category="linear",
                symbol=pair,
                interval=interval,
                limit=200
            )

            logger.debug(f"[DEBUG] RSI response type: {type(response)}, keys: {response.keys() if isinstance(response, dict) else 'not dict'}")

            if not isinstance(response, dict):
                logger.error(f"[ERROR] RSI response is not dict: {type(response)}")
                return None

            if response.get('retCode') != 0:
                logger.warning(f"[WARN] RSI API 에러 ({pair}): retCode={response.get('retCode')}, msg={response.get('retMsg', 'unknown')}")
                return None

            if not response['result']['list']:
                logger.warning(f"[WARN] RSI 데이터 없음 ({pair})")
                return None

            data_list = response['result']['list']
            data_list.reverse()

            if len(data_list) < period + 1:
                logger.warning(f"[WARN] RSI 데이터 부족 ({pair}): {len(data_list)}")
                return None

            close = np.array([float(x[4]) for x in data_list], dtype=float)

            delta = pd.Series(close).diff()
            gain = delta.copy()
            loss = delta.copy()

            gain[gain < 0] = 0
            loss[loss > 0] = 0
            loss = abs(loss)

            avg_gain = gain.rolling(window=period).mean()
            avg_loss = loss.rolling(window=period).mean()

            rs = avg_gain / (avg_loss + 0.001)
            rsi_values = 100 - (100 / (1 + rs))

            # pandas Series를 numpy array로 변환 후 인덱싱
            rsi_array = rsi_values.values
            rsi = float(rsi_array[-2]) if len(rsi_array) > 1 and not np.isnan(rsi_array[-2]) else None
            return rsi
        else:
            logger.warning(f"[WARN] Bybit 클라이언트 없음")
            return None
    except KeyError as ke:
        logger.error(f"[ERROR] RSI KeyError ({symbol}): key='{ke}', response keys might be: {list(response.keys()) if 'response' in locals() else 'unknown'}")
        import traceback
        logger.error(f"[TRACEBACK] {traceback.format_exc()}")
        return None
    except Exception as e:
        logger.error(f"[ERROR] RSI 계산 에러 ({symbol}): {type(e).__name__}: {e}")
        import traceback
        logger.error(f"[TRACEBACK] {traceback.format_exc()}")
        return None


def calculate_obv(symbol, timeframe=60):
    """Bybit에서 OBV 계산"""
    try:
        # 심볼 변환
        if symbol == "BTC":
            pair = "BTCUSDT"
        elif symbol == "ETH":
            pair = "ETHUSDT"
        else:
            pair = f"{symbol.upper()}USDT"

        # timeframe 변환
        if timeframe < 60:
            interval = str(timeframe)
        elif timeframe == 60:
            interval = "60"
        elif timeframe == 240:
            interval = "240"
        elif timeframe == 1440:
            interval = "1d"
        else:
            interval = "60"

        if config.bybit_client:
            response = config.bybit_client.get_kline(
                category="linear",
                symbol=pair,
                interval=interval,
                limit=200
            )

            if response['retCode'] != 0 or not response['result']['list']:
                return None, None

            data_list = response['result']['list']
            data_list.reverse()

            if len(data_list) < 21:
                return None, None

            close = np.array([float(x[4]) for x in data_list], dtype=float)
            volume = np.array([float(x[5]) for x in data_list], dtype=float)

            obv = np.zeros(len(close))
            obv[0] = volume[0]

            for i in range(1, len(close)):
                if close[i] > close[i-1]:
                    obv[i] = obv[i-1] + volume[i]
                elif close[i] < close[i-1]:
                    obv[i] = obv[i-1] - volume[i]
                else:
                    obv[i] = obv[i-1]

            avg_obv = pd.Series(obv).rolling(window=20).mean().values
            current_obv = float(obv[-2]) if len(obv) > 1 else None
            avg_obv_val = float(avg_obv[-2]) if len(avg_obv) > 1 and not pd.isna(avg_obv[-2]) else None

            return current_obv, avg_obv_val
        else:
            return None, None
    except Exception as e:
        logger.error(f"[ERROR] OBV 계산 에러: {symbol} - {e}")
        return None, None


def update_prices():
    """가격 업데이트 및 거래 체크 (백그라운드) - 모든 코인 지원"""
    from app.config import USERS_DIR
    logger.info("[INIT] 백그라운드 가격 업데이트 시작")

    while True:
        try:
            # 모든 사용자의 상태를 업데이트
            if os.path.exists(USERS_DIR):
                for username in os.listdir(USERS_DIR):
                    user_dir = os.path.join(USERS_DIR, username)
                    if not os.path.isdir(user_dir):
                        continue

                    try:
                        # 각 사용자의 상태 로드 (로컬 변수)
                        with state_transaction(username) as state:

                            # 사용 가능한 지갑 개수 확인
                            available_wallet_count = 0
                            if "wallets" in state:
                                for wallet in state["wallets"].values():
                                    if not wallet.get("is_active", False):
                                        available_wallet_count += 1

                            # 지갑이 모두 차면 기존 거래만 모니터링
                            skip_new_signals = available_wallet_count == 0

                            # 📅 캐시 타임스탐프 기반 동기화 (매 루프마다 확인)
                            import json
                            from datetime import datetime
                            from app.services import get_top_coins_by_volume_volatility

                            cache_file = os.path.join(os.path.dirname(__file__), "..", "..", "selected_coins_cache.json")
                            current_cache_timestamp = 0
                            cached_coins = None

                            # 현재 캐시 타임스탐프 읽기
                            if os.path.exists(cache_file):
                                try:
                                    with open(cache_file, 'r') as f:
                                        cache_data = json.load(f)
                                        current_cache_timestamp = cache_data.get("timestamp", 0)
                                        cached_coins = cache_data.get("coins", [])
                                except Exception as e:
                                    logger.warning(f"[WARN] 캐시 파일 읽기 실패: {e}")

                            # 마지막 확인한 캐시 타임스탐프와 비교
                            last_cache_timestamp = state.get("last_cache_timestamp", 0)

                            # 캐시가 새로 업데이트됐으면 즉시 로드
                            if current_cache_timestamp > last_cache_timestamp and cached_coins:
                                state["available_coins"] = cached_coins
                                state["last_cache_timestamp"] = current_cache_timestamp
                                logger.info(f"[INFO] 🔄 캐시 동기화: {cached_coins} (타임스탐프: {current_cache_timestamp})")
                                save_state(state, username)
                            elif not state.get("available_coins"):
                                # 캐시가 없으면 새로 선별
                                new_coins = get_top_coins_by_volume_volatility()
                                if new_coins:
                                    state["available_coins"] = new_coins
                                    state["last_cache_timestamp"] = datetime.now().timestamp()
                                    logger.info(f"[INFO] 📅 새로운 코인 자동 선별: {new_coins}")
                                    save_state(state, username)

                            # 선별된 코인 목록 (신호 체크할 전체 코인)
                            available_coins = state.get("available_coins", [])

                            # 거래할 코인 목록에 없는 코인은 state에서 제거 (중복 방지)
                            coins_to_remove = []
                            for key in list(state.keys()):
                                if isinstance(state[key], dict) and "last_close_time" in state[key]:
                                    coin = key
                                    # 거래 중인 코인이면 유지, 아니면 제거 예정
                                    if coin not in available_coins and not state[coin].get("position"):
                                        coins_to_remove.append(coin)

                            # 거래하지 않는 코인 제거
                            for coin in coins_to_remove:
                                del state[coin]
                                logger.info(f"[INFO] 거래 목록에서 제외된 코인 삭제: {coin.upper()}")

                            # 모든 선별된 코인 + 거래 중인 코인의 가격 업데이트 (거래 끝날 때까지 유지)
                            coins_to_update = set(available_coins)
                            for key in state.keys():
                                if isinstance(state[key], dict) and state[key].get("position"):
                                    coins_to_update.add(key)

                            for coin in coins_to_update:
                                try:
                                    # 심볼 매핑 (USD 쌍으로 변환)
                                    symbol = f"{coin.upper()}-USD"
                                    current_price = get_current_price(symbol)

                                    if current_price is not None:
                                        # 코인 상태 초기화 (처음 거래 전)
                                        if coin not in state:
                                            state[coin] = {
                                                "current_price": current_price,
                                                "position": None,
                                                "entry_price": None,
                                                "entry_time": None,
                                                "position_size": 0,
                                                "margin": 0,
                                                "profit": 0,
                                                "profit_pct": 0,
                                                "sl_price": None,
                                                "tp_price": None,
                                                "max_profit_price": None,
                                                "min_profit_price": None,
                                                "last_close_time": None,
                                                "timeframe": 60
                                            }

                                        state[coin]["current_price"] = current_price

                                        # 포지션 수익 계산 (거래 중인 경우)
                                        if state[coin]["position"]:
                                            if state[coin]["position"] == "long":
                                                state[coin]["profit"] = (current_price - state[coin]["entry_price"]) * state[coin]["position_size"]
                                                state[coin]["profit_pct"] = ((current_price - state[coin]["entry_price"]) / state[coin]["entry_price"]) * 100
                                            else:  # short
                                                state[coin]["profit"] = (state[coin]["entry_price"] - current_price) * state[coin]["position_size"]
                                                state[coin]["profit_pct"] = ((state[coin]["entry_price"] - current_price) / state[coin]["entry_price"]) * 100

                                        # 자동 거래 실행 (거래 활성화 시에만)
                                        # 지갑이 모두 차면: 기존 거래 중인 코인만 처리 (TP/SL 체크)
                                        # 지갑이 남으면: 모든 코인에서 신호 찾음
                                        if state.get("trading_enabled", False):
                                            if not skip_new_signals or state[coin].get("position"):
                                                auto_trade(coin, coin.upper(), state, username)
                                except Exception as e:
                                    logger.warning(f"[WARN] 코인 업데이트 실패 ({username}/{coin}): {e}")
                                    continue
                    except Exception as e:
                        logger.warning(f"[WARN] 사용자 업데이트 실패 ({username}): {e}")
                        continue

            time.sleep(2)  # 2초마다 업데이트
        except Exception as e:
            logger.error(f"[ERROR] 백그라운드 업데이트 중 오류: {e}")
            time.sleep(2)


def calculate_bollinger_bands(symbol, period=30, std_dev=2, timeframe=60):
    """Bollinger Band 계산 (기본 1시간봉 기반)
    2026-08-06: period 20 → 30 (1시간 이내 타임프레임은 30봉이 표준 기준).
    std도 pandas 기본값(ddof=1, 표본표준편차) 대신 calculate_band_width_average()의
    numpy std(ddof=0, 모집단표준편차)와 맞춰서 ddof=0으로 통일 - 안 맞추면 같은
    구간인데도 두 함수가 계산한 밴드폭이 미묘하게 어긋나는 문제가 있었음.
    2026-08-10: 15분봉 하드코딩 → timeframe 파라미터 추가(기본 60=1시간봉). 진입필터/청산
    로직은 이미 1시간봉으로 바뀌었는데 스퀴즈/브레이크아웃 신호만 15분봉이라 시간대가
    섞여있던 문제를 해소 - check_bollinger_band_signal에서 60으로 호출."""
    try:
        if not config.bybit_client:
            return None
        if symbol == "BTC":
            pair = "BTCUSDT"
        elif symbol == "ETH":
            pair = "ETHUSDT"
        else:
            pair = f"{symbol.upper()}USDT"

        # timeframe을 분에서 Bybit interval로 변환 (calculate_hma와 동일 규칙)
        if timeframe < 60:
            interval = str(timeframe)
        elif timeframe == 60:
            interval = "60"
        elif timeframe == 240:
            interval = "240"
        elif timeframe == 1440:
            interval = "1d"
        else:
            interval = "60"

        response = config.bybit_client.get_kline(
            category="linear",
            symbol=pair,
            interval=interval,
            limit=max(period + 50, 100)
        )

        if response['retCode'] != 0 or not response['result']['list']:
            return None

        data_list = response['result']['list']
        data_list.reverse()

        close = np.array([float(x[4]) for x in data_list], dtype=float)

        sma = pd.Series(close).rolling(window=period).mean().values
        std = pd.Series(close).rolling(window=period).std(ddof=0).values

        upper_band = sma + (std_dev * std)
        lower_band = sma - (std_dev * std)

        current_close = close[-2] if len(close) > 1 else close[-1]
        current_sma = sma[-2] if len(sma) > 1 and not pd.isna(sma[-2]) else None
        current_upper = upper_band[-2] if len(upper_band) > 1 and not pd.isna(upper_band[-2]) else None
        current_lower = lower_band[-2] if len(lower_band) > 1 and not pd.isna(lower_band[-2]) else None

        if current_sma is None or current_upper is None or current_lower is None:
            return None

        return {
            "close": current_close,
            "sma": current_sma,
            "upper": current_upper,
            "lower": current_lower,
            "width": current_upper - current_lower
        }

    except Exception as e:
        logger.error(f"[ERROR] Bollinger Band 계산 에러: {symbol} - {e}")
        return None


def calculate_band_width_average(symbol, lookback=30, timeframe=60):
    """Band Width 평균 계산 - 변동성 확인 + 마지막 완성 캔들의 시가/종가(방향 판정용)
    2026-08-06: lookback 10/20 → 30으로 통일 (calculate_bollinger_bands의 period=30과
    동일 기준). np.std()는 원래부터 기본값이 ddof=0(모집단)이라 이 함수는 그대로 두고,
    pandas 쪽(calculate_bollinger_bands)을 ddof=0으로 맞춰서 둘이 어긋나지 않게 함.
    2026-08-10: 15분봉 하드코딩 → timeframe 파라미터 추가(기본 60=1시간봉). calculate_bollinger_bands와
    동일 이유(신호-필터 시간대 통일)."""
    try:
        if not config.bybit_client:
            return None

        if symbol == "BTC":
            pair = "BTCUSDT"
        elif symbol == "ETH":
            pair = "ETHUSDT"
        else:
            pair = f"{symbol.upper()}USDT"

        # timeframe을 분에서 Bybit interval로 변환 (calculate_hma와 동일 규칙)
        if timeframe < 60:
            interval = str(timeframe)
        elif timeframe == 60:
            interval = "60"
        elif timeframe == 240:
            interval = "240"
        elif timeframe == 1440:
            interval = "1d"
        else:
            interval = "60"

        response = config.bybit_client.get_kline(
            category="linear",
            symbol=pair,
            interval=interval,
            limit=max(lookback * 3, 100)
        )

        if response['retCode'] != 0 or not response['result']['list']:
            return None

        data_list = response['result']['list']
        data_list.reverse()

        if len(data_list) < 2:
            return None

        close = np.array([float(x[4]) for x in data_list], dtype=float)

        widths = []
        for i in range(len(close) - lookback):
            segment = close[i:i+lookback]
            sma = np.mean(segment)
            std = np.std(segment)
            upper = sma + (2 * std)
            lower = sma - (2 * std)
            width = upper - lower
            widths.append(width)

        avg_width = np.mean(widths) if widths else None
        current_width = widths[-1] if widths else None

        if avg_width is None or current_width is None:
            return None

        # 마지막으로 완성된 캔들 (진행 중인 캔들 제외 - 인덱스 -2)
        candle_open = float(data_list[-2][1])
        candle_close = float(data_list[-2][4])
        candle_time = data_list[-2][0]  # 완성 캔들 시작 타임스탬프(ms, 문자열) - 캔들 식별용

        return {
            "avg_width": avg_width,
            "current_width": current_width,
            "is_high_volatility": current_width > avg_width,
            "candle_open": candle_open,
            "candle_close": candle_close,
            "candle_time": candle_time
        }

    except Exception as e:
        logger.error(f"[ERROR] Band Width 평균 계산 에러: {symbol} - {e}")
        return None
