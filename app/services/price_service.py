"""가격 조회 및 기술적 분석"""
import os
import time
import logging
import threading
import yfinance as yf
import pandas as pd
import numpy as np
from app.config import bybit_client
from app.utils import (
    load_state,
    save_state,
    load_trades,
    save_trades,
    format_price
)
from .trading_service import auto_trade

logger = logging.getLogger(__name__)


def get_current_price(symbol):
    """Bybit에서 현재 가격 조회 - 현물 마진 거래"""
    try:
        if bybit_client:
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

            # Spot 마켓에서 가격 조회
            response = bybit_client.get_tickers(category="spot", symbol=pair)

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
        if bybit_client:
            response = bybit_client.get_kline(
                category="spot",
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
        if bybit_client:
            response = bybit_client.get_kline(
                category="spot",
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
                        state = load_state(username)

                        # 선별된 코인 목록 (신호 체크할 전체 코인)
                        available_coins = state.get("available_coins", [])

                        # 모든 선별된 코인에 대해 가격 업데이트 및 신호 체크
                        for coin in available_coins:
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
                                    if state.get("trading_enabled", False):
                                        auto_trade(coin, coin.upper(), state, username)
                            except Exception as e:
                                logger.warning(f"[WARN] 코인 업데이트 실패 ({username}/{coin}): {e}")
                                continue

                        # 각 사용자의 상태 저장
                        save_state(state, username)
                    except Exception as e:
                        logger.warning(f"[WARN] 사용자 업데이트 실패 ({username}): {e}")
                        continue

            time.sleep(10)  # 10초마다 업데이트
        except Exception as e:
            logger.error(f"[ERROR] 백그라운드 업데이트 중 오류: {e}")
            time.sleep(10)
