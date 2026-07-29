from flask import Flask, render_template, jsonify, request, session
import yfinance as yf
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timedelta
import threading
import time
from dotenv import load_dotenv
from pybit.unified_trading import HTTP
import uuid
import hashlib
import logging
from filelock import FileLock
from pathlib import Path
import jwt
from functools import wraps

# 로거 설정
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# secrets.env 로드 (여러 경로 지원)
secrets_paths = [
    'C:\\Users\\protre\\codex-secrets\\secrets.env',  # Windows
    '/home/protre/codex-secrets/secrets.env',  # Linux
    '.env'  # 현재 디렉토리
]
for secrets_path in secrets_paths:
    if os.path.exists(secrets_path):
        load_dotenv(secrets_path)
        logger.info(f"[INIT] Loaded secrets from: {secrets_path}")
        break

# Bybit API 초기화
BYBIT_API_KEY = os.getenv('key')
BYBIT_API_SECRET = os.getenv('secret')

if not BYBIT_API_KEY or not BYBIT_API_SECRET:
    logger.warning("[WARN] Bybit API 키가 설정되지 않았습니다. 환경변수를 확인하세요.")
    BYBIT_API_KEY = None
    BYBIT_API_SECRET = None

bybit_client = None
if BYBIT_API_KEY and BYBIT_API_SECRET:
    try:
        bybit_client = HTTP(
            testnet=False,
            api_key=BYBIT_API_KEY,
            api_secret=BYBIT_API_SECRET
        )
        logger.info("[INIT] Bybit API 연결 성공")
    except Exception as e:
        logger.error(f"[ERROR] Bybit API 연결 실패: {e}")
        bybit_client = None
else:
    logger.warning("[WARN] Bybit API 키 없음 - Paper Trade 모드로 실행 중")

# 절대 경로로 templates 폴더 지정
template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
app = Flask(__name__, template_folder=template_dir)

# JWT 설정
JWT_SECRET = 'bybit-bot-jwt-secret-2026'
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION = 86400 * 7  # 7일

# 세션 설정 (JWT 토큰 기반 인증으로 변경)
app.config['SECRET_KEY'] = JWT_SECRET
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# 사용자 데이터 디렉토리 및 Lock
USERS_DIR = "users"
USERS_FILE = "users.json"
USERS_LOCK_FILE = "users.json.lock"
os.makedirs(USERS_DIR, exist_ok=True)

# 전역 Lock 객체 (스레드 안전성)
_state_lock = threading.RLock()
_file_locks = {}

# 사용자 관리 함수
def get_user_data_dir(username):
    """사용자 데이터 디렉토리 경로"""
    user_dir = os.path.join(USERS_DIR, username)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

def get_user_files(username):
    """사용자별 파일 경로"""
    user_dir = get_user_data_dir(username)
    return {
        'state': os.path.join(user_dir, 'bot_state.json'),
        'trades': os.path.join(user_dir, 'trades.json')
    }

def load_users():
    """사용자 목록 로드 (Thread-safe)"""
    try:
        lock_file = FileLock(USERS_LOCK_FILE, timeout=5)
        with lock_file:
            if os.path.exists(USERS_FILE):
                with open(USERS_FILE, 'r') as f:
                    return json.load(f)
    except Exception as e:
        logger.error(f"[ERROR] 사용자 목록 로드 실패: {e}")
    return {}

def save_users(users):
    """사용자 목록 저장 (Thread-safe)"""
    try:
        lock_file = FileLock(USERS_LOCK_FILE, timeout=5)
        with lock_file:
            with open(USERS_FILE, 'w') as f:
                json.dump(users, f, indent=2)
    except Exception as e:
        logger.error(f"[ERROR] 사용자 목록 저장 실패: {e}")

def hash_password(password):
    """비밀번호 해싱"""
    return hashlib.sha256(password.encode()).hexdigest()

def get_current_user():
    """현재 로그인한 사용자 반환 (JWT 토큰 기반)"""
    try:
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return None

        token = auth_header.split(' ')[1]
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get('username')
    except:
        return None

def token_required(f):
    """JWT 토큰 검증 데코레이터"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization', '')

        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]

        if not token:
            return jsonify({"error": "인증 토큰이 필요합니다"}), 401

        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            username = payload.get('username')
            if not username:
                return jsonify({"error": "유효하지 않은 토큰입니다"}), 401
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "토큰이 만료되었습니다"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "유효하지 않은 토큰입니다"}), 401

        return f(*args, **kwargs)
    return decorated

# 기본 코인 설정 템플릿
def create_default_coin_state(coin_name):
    """새 코인의 기본 상태 생성"""
    return {
        "position": None,
        "entry_price": None,
        "entry_time": None,
        "current_price": 0,
        "margin": 1000,
        "leverage": 10,
        "position_size": 0,
        "profit": 0,
        "profit_pct": 0,
        "max_profit_price": None,
        "timeframe": 60,
        "position_ratio": 75,
        "tp": 2.0,
        "sl": 1.5,
        "last_close_time": None  # 거래 종료 시간 (반복 진입 방지용)
    }

# 기본 상태 (coins는 register에서만 초기화!)
DEFAULT_STATE = {
    "mode": "paper",
    "coins": [],  # 초기화 후 코인 유지를 위해 빈 배열로 시작
    "total_seed": 3000,
}

def _get_file_lock(filepath):
    """파일별 Lock 객체 획득 (캐싱)"""
    if filepath not in _file_locks:
        _file_locks[filepath] = FileLock(f"{filepath}.lock", timeout=5)
    return _file_locks[filepath]

def load_state(username=None):
    """저장된 상태 로드 또는 기본값 반환 (Thread-safe)"""
    if username is None:
        username = get_current_user() or 'guest'

    user_files = get_user_files(username)
    state_file = user_files['state']

    try:
        lock = _get_file_lock(state_file)
        with lock:
            if os.path.exists(state_file):
                with open(state_file, 'r') as f:
                    return json.load(f)
    except Exception as e:
        logger.error(f"[ERROR] 상태 로드 실패 ({username}): {e}")
    return DEFAULT_STATE.copy()

def save_state(state_data, username=None):
    """상태를 파일에 저장 (Thread-safe)"""
    if username is None:
        username = get_current_user() or 'guest'

    user_files = get_user_files(username)
    state_file = user_files['state']

    try:
        lock = _get_file_lock(state_file)
        with lock:
            os.makedirs(os.path.dirname(state_file), exist_ok=True)
            with open(state_file, 'w') as f:
                json.dump(state_data, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"[ERROR] 상태 저장 실패 ({username}): {e}")


def load_trades(username=None):
    """거래 기록 로드 (Thread-safe)"""
    if username is None:
        username = get_current_user() or 'guest'

    user_files = get_user_files(username)
    trades_file = user_files['trades']

    try:
        lock = _get_file_lock(trades_file)
        with lock:
            if os.path.exists(trades_file):
                with open(trades_file, 'r') as f:
                    return json.load(f)
    except Exception as e:
        logger.error(f"[ERROR] 거래 기록 로드 실패 ({username}): {e}")
    return []

def save_trades(trades, username=None):
    """거래 기록 저장 (Thread-safe)"""
    if username is None:
        username = get_current_user() or 'guest'

    user_files = get_user_files(username)
    trades_file = user_files['trades']

    try:
        lock = _get_file_lock(trades_file)
        with lock:
            os.makedirs(os.path.dirname(trades_file), exist_ok=True)
            with open(trades_file, 'w') as f:
                json.dump(trades, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"[ERROR] 거래 기록 저장 실패 ({username}): {e}")

def format_price(price, coin=None):
    """Bybit API에서 받은 가격을 그대로 사용 (소수점 제한 없음)"""
    if price is None:
        return 0.0
    return float(price)

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
            # Bybit 연결 실패시 yfinance 폴백
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
        print(f"[DEBUG] ATR 계산 에러: {symbol} - {e}")
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
        print(f"[DEBUG] SMA 계산 에러: {symbol} - {e}")
        return None

def check_entry_signal(symbol, coin_key, state):
    """진입 신호 확인 (전봉 기준)"""
    try:
        current_price = state[coin_key]["current_price"]
        timeframe = state[coin_key].get("timeframe", 60)

        # 전봉(완성된 캔들) 기준으로 계산
        atr = calculate_atr(symbol, timeframe=timeframe)
        sma = calculate_sma(symbol, timeframe=timeframe)

        if atr is None or sma is None:
            return None

        # 이전 완성 캔들의 ATR/SMA 기반으로 신호 생성
        upper_breakout = sma + (atr * 1.5)
        lower_breakout = sma - (atr * 1.5)

        # 현재 가격이 이전 캔들의 저항선/지지선을 돌파했는지 확인
        if current_price < lower_breakout:
            return "short"
        elif current_price > upper_breakout:
            return "long"

        return None
    except Exception as e:
        print(f"[ERROR] check_entry_signal ({coin_key}): {e}")
        return None

def auto_trade(coin_key, symbol, state, username=None):
    """자동 거래 로직 (전봉 기준)"""
    try:
        current_price = state[coin_key]["current_price"]

        if current_price == 0:
            return

        # ⭐ 거래 종료 후 5분 이내는 자동 거래 비활성화 (반복 진입 방지)
        if "last_close_time" in state[coin_key] and state[coin_key]["last_close_time"]:
            try:
                last_close_time = datetime.fromisoformat(state[coin_key]["last_close_time"])
                elapsed = (datetime.now() - last_close_time).total_seconds()
                if elapsed < 300:  # 300초 = 5분
                    return
            except:
                pass

        # 거래 진입 후 최소 1분은 TP/SL 체크 안함 (안정화 대기)
        if state[coin_key]["position"] and state[coin_key]["entry_time"]:
            try:
                entry_time = datetime.fromisoformat(state[coin_key]["entry_time"])
                elapsed = (datetime.now() - entry_time).total_seconds()
                if elapsed < 60:  # 60초 이내는 TP/SL 체크 안함
                    return
            except:
                pass

        # TP/SL 체크
        if state[coin_key]["position"]:
            # 코인별 설정에서 TP/SL 가져오기
            coin_settings = state.get("coin_settings", {}).get(coin_key, {})
            tp_percent = coin_settings.get("tp", 2.0) / 100
            sl_percent = coin_settings.get("sl", 1.5) / 100

            if state[coin_key]["position"] == "long":
                # 최고가 추적
                if current_price > state[coin_key]["max_profit_price"]:
                    state[coin_key]["max_profit_price"] = current_price

                tp_price = state[coin_key]["entry_price"] * (1 + tp_percent)
                sl_price = state[coin_key]["entry_price"] * (1 - sl_percent)

                # 익절 또는 손절
                if current_price >= tp_price:
                    close_trade(coin_key, current_price, "Take Profit", state, username)
                elif current_price <= sl_price:
                    close_trade(coin_key, sl_price, "Stop Loss", state, username)

            elif state[coin_key]["position"] == "short":
                # 최저가 추적
                if current_price < state[coin_key]["max_profit_price"]:
                    state[coin_key]["max_profit_price"] = current_price

                tp_price = state[coin_key]["entry_price"] * (1 - tp_percent)
                sl_price = state[coin_key]["entry_price"] * (1 + sl_percent)

                # 익절 또는 손절
                if current_price <= tp_price:
                    close_trade(coin_key, current_price, "Take Profit", state, username)
                elif current_price >= sl_price:
                    close_trade(coin_key, sl_price, "Stop Loss", state, username)

        # 진입 신호
        if not state[coin_key]["position"]:
            signal = check_entry_signal(symbol, coin_key, state)
            if signal:
                # 코인별 설정에서 시드와 레버리지 가져오기
                coin_settings = state.get("coin_settings", {}).get(coin_key, {})
                current_seed = coin_settings.get("current_seed", coin_settings.get("initial_seed", 1000))
                entry_percent = coin_settings.get("entry_percent", 75) / 100
                leverage = coin_settings.get("leverage", 10)

                # 코인별 시드에서만 진입
                if current_seed > 0:
                    state[coin_key]["position"] = signal
                    state[coin_key]["entry_price"] = current_price
                    state[coin_key]["entry_time"] = datetime.now().isoformat()
                    state[coin_key]["max_profit_price"] = current_price

                    # 코인별 설정에 따라 포지션 계산
                    position_nominal = current_seed * entry_percent * leverage
                    state[coin_key]["position_size"] = position_nominal / current_price

                    logger.info(f"[{coin_key.upper()}] {signal.upper()} 진입: {current_price} (시드: ${current_seed}, 진입: {entry_percent*100}%, 레버리지: {leverage}x)")
                else:
                    logger.warning(f"[{coin_key.upper()}] 경고: 시드가 부족하여 진입 불가")
    except Exception as e:
        logger.error(f"[ERROR] auto_trade ({coin_key}): {e}")

def close_trade(coin_key, exit_price, reason, state, username=None):
    """거래 종료 및 기록"""
    try:
        if state[coin_key]["position"] == "long":
            profit = (exit_price - state[coin_key]["entry_price"]) * state[coin_key]["position_size"]
        else:  # short
            profit = (state[coin_key]["entry_price"] - exit_price) * state[coin_key]["position_size"]

        # 수익률은 실제 사용된 자금(margin * position_ratio)을 기준으로 계산
        actual_used_capital = state[coin_key]["margin"] * (state[coin_key]["position_ratio"] / 100)
        profit_pct = ((profit / actual_used_capital) * 100) if actual_used_capital > 0 else 0

        # 거래 기록 저장
        trades = load_trades(username)

        # 실제 손실/수익 기반으로 재계산하여 일관성 확보
        actual_position_size = state[coin_key]["position_size"]
        actual_entry_price = state[coin_key]["entry_price"]
        actual_profit = profit
        actual_profit_pct = profit_pct

        trade = {
            "coin": coin_key.upper(),
            "type": state[coin_key]["position"].upper(),
            "entry_price": round(actual_entry_price, 6),  # 더 정확한 소수점
            "exit_price": round(exit_price, 6),
            "entry_time": state[coin_key]["entry_time"],
            "exit_time": datetime.now().isoformat(),
            "profit": round(profit, 2),
            "profit_pct": round(profit_pct, 2),
            "position_size": round(actual_position_size, 8),  # 더 정확한 소수점
            "reason": reason
        }
        trades.append(trade)
        save_trades(trades, username)

        # 코인별 시드 업데이트
        if "coin_settings" not in state:
            state["coin_settings"] = {}
        if coin_key not in state["coin_settings"]:
            state["coin_settings"][coin_key] = {}

        current_seed = state["coin_settings"][coin_key].get("current_seed", 1000)
        state["coin_settings"][coin_key]["current_seed"] = current_seed + profit

        # 마진 업데이트 (하위 호환성 유지)
        state[coin_key]["margin"] += profit

        # 총시드 업데이트
        state["total_seed"] += profit

        # 포지션 리셋
        state[coin_key]["position"] = None
        state[coin_key]["entry_price"] = None
        state[coin_key]["entry_time"] = None
        state[coin_key]["profit"] = 0
        state[coin_key]["profit_pct"] = 0
        state[coin_key]["position_size"] = 0
        state[coin_key]["max_profit_price"] = None
        # ⭐ 거래 종료 후 5분간 자동 거래 비활성화 (반복 방지)
        state[coin_key]["last_close_time"] = datetime.now().isoformat()

        logger.info(f"[{coin_key.upper()}] 거래 종료: {reason}, 수익: ${profit:.2f}")
    except Exception as e:
        logger.error(f"[ERROR] close_trade ({coin_key}): {e}")

def update_prices():
    """가격 업데이트 및 거래 체크 (백그라운드) - 모든 코인 지원"""
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
                        with _state_lock:
                            # 각 사용자의 상태 로드 (로컬 변수)
                            state = load_state(username)

                            # 모든 활성 코인에 대해 가격 업데이트
                            for coin in state.get("coins", []):
                                if coin not in state:
                                    continue

                                try:
                                    # 심볼 매핑 (USD 쌍으로 변환)
                                    symbol = f"{coin.upper()}-USD"
                                    current_price = get_current_price(symbol)

                                    if current_price is not None:
                                        state[coin]["current_price"] = current_price

                                        # 포지션 수익 계산
                                        if state[coin]["position"]:
                                            if state[coin]["position"] == "long":
                                                state[coin]["profit"] = (current_price - state[coin]["entry_price"]) * state[coin]["position_size"]
                                                state[coin]["profit_pct"] = ((current_price - state[coin]["entry_price"]) / state[coin]["entry_price"]) * 100
                                            else:  # short
                                                state[coin]["profit"] = (state[coin]["entry_price"] - current_price) * state[coin]["position_size"]
                                                state[coin]["profit_pct"] = ((state[coin]["entry_price"] - current_price) / state[coin]["entry_price"]) * 100

                                        # 자동 거래 실행
                                        if state["mode"] == "paper":
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

# ==================== 인증 API ====================

@app.route('/api/auth/register', methods=['POST'])
def register():
    """회원가입"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()

        if not username or not password:
            return jsonify({"error": "사용자명과 비밀번호를 입력해주세요"}), 400

        users = load_users()

        if username in users:
            return jsonify({"error": "이미 존재하는 사용자명입니다"}), 400

        # 사용자 등록
        users[username] = {
            "password_hash": hash_password(password),
            "created_at": datetime.now().isoformat()
        }
        save_users(users)

        # 사용자 디렉토리 생성
        get_user_data_dir(username)

        # 새 사용자의 초기 상태 생성 (첫 로그인 시에만 BTC/ETH/ADA 기본값 설정)
        initial_state = {
            "mode": "paper",
            "coins": ["btc", "eth", "ada"],
            "total_seed": 3000
        }
        for coin in initial_state["coins"]:
            initial_state[coin] = create_default_coin_state(coin)
        save_state(initial_state, username)

        logger.info(f"[INFO] 새 사용자 등록: {username}")

        return jsonify({
            "success": True,
            "message": f"{username} 사용자로 가입되었습니다"
        }), 201

    except Exception as e:
        logger.error(f"[ERROR] register: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/auth/login', methods=['POST'])
def login():
    """로그인"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()

        if not username or not password:
            return jsonify({"error": "사용자명과 비밀번호를 입력해주세요"}), 400

        users = load_users()

        if username not in users:
            return jsonify({"error": "존재하지 않는 사용자명입니다"}), 401

        # 비밀번호 확인
        if users[username]["password_hash"] != hash_password(password):
            return jsonify({"error": "비밀번호가 일치하지 않습니다"}), 401

        # JWT 토큰 생성
        import datetime
        import time
        now = int(time.time())
        payload = {
            'username': username,
            'jti': str(uuid.uuid4()),  # 각 토큰마다 유니크한 ID
            'iat': now,
            'exp': now + (86400 * 7)  # 7일
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        # PyJWT 버전에 따라 bytes 또는 str 반환 → 항상 str로 통일
        if isinstance(token, bytes):
            token = token.decode('utf-8')

        # 상태 초기화 (사용자별 상태 로드)
        state_data = load_state(username)

        # 상태에 없는 코인들의 데이터만 초기화 (기존 코인 유지!)
        for coin in state_data.get("coins", []):
            if coin not in state_data:
                state_data[coin] = create_default_coin_state(coin)

            # 초기 가격 로드
            symbol = f"{coin.upper()}-USD"
            price = get_current_price(symbol)
            if price:
                state_data[coin]["current_price"] = price

        # 로그인 후 상태 저장
        save_state(state_data, username)

        logger.info(f"[INFO] 사용자 로그인: {username}")

        return jsonify({
            "success": True,
            "message": f"{username}으로 로그인되었습니다",
            "username": username,
            "token": token
        })

    except Exception as e:
        logger.error(f"[ERROR] login: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """로그아웃 (JWT는 클라이언트에서 토큰 삭제)"""
    try:
        # JWT는 stateless이므로 서버에서 추가 작업 불필요
        # 클라이언트에서 로컬스토리지의 토큰을 삭제
        return jsonify({
            "success": True,
            "message": "로그아웃되었습니다"
        })

    except Exception as e:
        logger.error(f"[ERROR] logout: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/auth/check', methods=['GET'])
def check_auth():
    """현재 로그인 상태 확인 (JWT 토큰 기반)"""
    try:
        user = get_current_user()
        if user:
            return jsonify({
                "authenticated": True,
                "username": user
            })
        else:
            return jsonify({
                "authenticated": False
            })

    except Exception as e:
        logger.error(f"[ERROR] check_auth: {e}")
        return jsonify({"authenticated": False})


# ==================== 메인 라우트 ====================

@app.route('/')
def index():
    """메인 페이지"""
    from flask import make_response
    response = make_response(render_template('index.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/login')
@app.route('/login.html')
def login_page():
    """로그인 페이지"""
    from flask import make_response
    response = make_response(render_template('login.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/api/status')
@token_required
def get_status():
    """현재 상태 조회 (모든 코인)"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    result = {}
    total_profit = 0
    total_margin = 0

    # 모든 활성 코인의 상태를 반환
    for coin in state.get("coins", []):
        if coin in state:
            coin_data = state[coin]
            result[coin] = {
                "current_price": coin_data["current_price"],  # Bybit API 원본 그대로
                "position": coin_data["position"],
                "entry_price": coin_data["entry_price"] if coin_data["entry_price"] else 0,  # 원본 그대로
                "margin": round(coin_data["margin"], 2),
                "profit": round(coin_data["profit"], 2),
                "profit_pct": round(coin_data["profit_pct"], 2),
                "entry_time": coin_data["entry_time"]
            }
            total_profit += coin_data["profit"]
            total_margin += coin_data["margin"]

    total_margin += total_profit

    result["total"] = {
        "profit": round(total_profit, 2),
        "margin": round(total_margin, 2),
        "initial_capital": state.get("total_seed", 3000)
    }
    result["coins"] = state.get("coins", [])
    result["total_seed"] = state.get("total_seed", 3000)

    return jsonify(result)

@app.route('/api/sell/<coin>', methods=['POST'])
@token_required
def sell_position(coin):
    """포지션 매도"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    coin = coin.lower()
    if coin not in state.get("coins", []):
        return jsonify({"error": "Invalid coin"}), 400

    if coin not in state or not state[coin]["position"]:
        return jsonify({"error": "No open position"}), 400

    # 현재 가격으로 매도
    exit_price = state[coin]["current_price"]
    profit = state[coin]["profit"]

    # 거래 기록 저장
    trades = load_trades(username)

    # 수익률은 실제 사용된 자금 기준으로 계산
    actual_used_capital = state[coin]["margin"] * (state[coin]["position_ratio"] / 100)
    profit_pct = ((profit / actual_used_capital) * 100) if actual_used_capital > 0 else 0

    trade = {
        "coin": coin.upper(),
        "type": state[coin]["position"].upper(),
        "entry_price": round(state[coin]["entry_price"], 6),
        "exit_price": round(exit_price, 6),
        "entry_time": state[coin]["entry_time"],
        "exit_time": datetime.now().isoformat(),
        "profit": round(profit, 2),
        "profit_pct": round(profit_pct, 2),
        "position_size": round(state[coin]["position_size"], 8)
    }
    trades.append(trade)
    save_trades(trades, username)

    # 마진 업데이트
    state[coin]["margin"] += profit

    # 총시드 업데이트 (손실/수익이 총시드에 반영)
    state["total_seed"] += profit

    # 포지션 리셋
    state[coin]["position"] = None
    state[coin]["entry_price"] = None
    state[coin]["entry_time"] = None
    state[coin]["profit"] = 0
    state[coin]["profit_pct"] = 0
    state[coin]["position_size"] = 0
    # ⭐ 강제 매도 후 5분간 자동 거래 비활성화 (반복 방지)
    state[coin]["last_close_time"] = datetime.now().isoformat()

    # 상태 저장
    save_state(state, username)

    return jsonify({
        "success": True,
        "message": f"{coin.upper()} position closed",
        "profit": round(profit, 2),
        "new_margin": round(state[coin]["margin"], 2),
        "trade": trade
    })

@app.route('/api/trades')
@token_required
def get_trades():
    """거래 기록 조회"""
    username = get_current_user() or 'guest'
    trades = load_trades(username)
    return jsonify(trades)

@app.route('/api/stats')
@token_required
def get_stats():
    """통계"""
    username = get_current_user() or 'guest'
    trades = load_trades(username)

    if not trades:
        return jsonify({
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "win_rate": 0,
            "total_profit": 0,
            "avg_profit": 0
        })

    win_trades = len([t for t in trades if t.get("profit", 0) > 0])
    loss_trades = len([t for t in trades if t.get("profit", 0) < 0])
    total_profit = sum([t.get("profit", 0) for t in trades])

    return jsonify({
        "total_trades": len(trades),
        "win_trades": win_trades,
        "loss_trades": loss_trades,
        "win_rate": round((win_trades / len(trades) * 100), 1) if trades else 0,
        "total_profit": round(total_profit, 2),
        "avg_profit": round(total_profit / len(trades), 2) if trades else 0
    })

@app.route('/api/mode')
@token_required
def get_mode():
    """현재 모드"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    return jsonify({"mode": state["mode"]})

@app.route('/api/mode/<mode>', methods=['POST'])
@token_required
def set_mode(mode):
    """모드 변경"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    if mode in ["paper", "live"]:
        state["mode"] = mode
        save_state(state, username)
        return jsonify({"success": True, "mode": state["mode"]})
    return jsonify({"error": "Invalid mode"}), 400

@app.route('/api/reset', methods=['POST'])
@token_required
def reset_all():
    """모든 상태 초기화 - 모든 코인 삭제"""
    try:
        username = get_current_user() or 'guest'
        state = load_state(username)

        trades = load_trades(username)
        total_profit = sum([t.get("profit", 0) for t in trades])

        # 파일 초기화
        save_trades([], username)

        # 현재 활성 코인 목록 저장
        active_coins = state.get("coins", [])

        # 모든 코인의 상태 초기화
        for coin in active_coins:
            if coin in state:
                state[coin]["position"] = None
                state[coin]["entry_price"] = None
                state[coin]["entry_time"] = None
                state[coin]["margin"] = 0
                state[coin]["position_size"] = 0
                state[coin]["profit"] = 0
                state[coin]["profit_pct"] = 0
                state[coin]["max_profit_price"] = None

        # 모든 코인 삭제 - 사용자가 직접 추가해야만 거래 가능
        state["coins"] = []

        # 상태 저장 (사용자명 전달!)
        save_state(state, username)

        logger.info(f"[INFO] 시스템 초기화: 누적 수익 ${total_profit:.2f}, 모든 코인 삭제됨")

        return jsonify({
            "success": True,
            "message": "시스템 초기화 완료 - 모든 코인이 삭제되었습니다. 다시 거래하려면 코인을 추가해주세요.",
            "total_profit_accumulated": round(total_profit, 2),
            "coins": []
        })
    except Exception as e:
        logger.error(f"[ERROR] reset_all 함수 오류: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/settings', methods=['GET'])
@token_required
def get_all_settings():
    """모든 코인 설정 조회"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    result = {}
    for coin in state.get("coins", []):
        if coin in state:
            result[coin] = {
                "leverage": state[coin].get("leverage", 10),
                "margin": state[coin].get("margin", 1000),
                "position_ratio": state[coin].get("position_ratio", 75),
                "tp": state[coin].get("tp", 2.0),
                "sl": state[coin].get("sl", 1.5),
                "timeframe": state[coin].get("timeframe", 60)
            }
    return jsonify(result)

@app.route('/api/settings/<coin>', methods=['GET'])
@token_required
def get_settings(coin):
    """코인 설정 조회"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    coin = coin.lower()
    if coin not in state.get("coins", []):
        return jsonify({"error": "Invalid coin"}), 400

    if coin not in state:
        return jsonify({"error": "Coin not found"}), 404

    return jsonify({
        "leverage": state[coin].get("leverage", 10),
        "margin": state[coin].get("margin", 1000),
        "position_ratio": state[coin].get("position_ratio", 75),
        "tp": state[coin].get("tp", 2.0),
        "sl": state[coin].get("sl", 1.5),
        "timeframe": state[coin].get("timeframe", 60)
    })

@app.route('/api/settings/<coin>', methods=['POST'])
@token_required
def set_settings(coin):
    """코인 설정 저장"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    coin = coin.lower()
    if coin not in state.get("coins", []):
        return jsonify({"error": "Invalid coin"}), 400

    if coin not in state:
        return jsonify({"error": "Coin not found"}), 404

    data = request.get_json()

    if "timeframe" in data:
        state[coin]["timeframe"] = int(data["timeframe"])
    if "margin" in data:
        state[coin]["margin"] = float(data["margin"])
    if "leverage" in data:
        state[coin]["leverage"] = int(data["leverage"])
    if "position_ratio" in data:
        state[coin]["position_ratio"] = float(data["position_ratio"])
    if "tp" in data:
        state[coin]["tp"] = float(data["tp"])
    if "sl" in data:
        state[coin]["sl"] = float(data["sl"])

    # 파일에 저장
    save_state(state, username)

    return jsonify({
        "success": True,
        "settings": {
            "leverage": state[coin].get("leverage", 10),
            "margin": state[coin].get("margin", 1000),
            "position_ratio": state[coin].get("position_ratio", 75),
            "tp": state[coin].get("tp", 2.0),
            "sl": state[coin].get("sl", 1.5),
            "timeframe": state[coin].get("timeframe", 60)
        }
    })

@app.route('/api/coins', methods=['GET'])
@token_required
def get_coins():
    """활성 코인 목록 조회"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    coins = state.get("coins", [])
    # coins는 사용자가 지정한 대로 반환 (빈 배열일 수도 있음)
    return jsonify({"coins": coins})


@app.route('/api/global-settings', methods=['GET'])
@token_required
def get_global_settings():
    """전역 설정 조회"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    return jsonify({
        "total_seed": state.get("total_seed", 3000),
        "coins": state.get("coins", [])
    })

@app.route('/api/global-settings', methods=['POST'])
@token_required
def set_global_settings():
    """전역 설정 저장"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    data = request.get_json()

    if "total_seed" in data:
        state["total_seed"] = float(data["total_seed"])

    # 상태 저장
    save_state(state, username)

    return jsonify({
        "success": True,
        "total_seed": state.get("total_seed", 3000)
    })

@app.route('/api/calendar/<int:year>/<int:month>', methods=['GET'])
@token_required
def get_calendar_data(year, month):
    """달력 데이터 조회 (날짜별 수익금)"""
    username = get_current_user() or 'guest'
    trades = load_trades(username)

    # 날짜별 수익금 집계
    daily_profit = {}
    for trade in trades:
        try:
            entry_date = datetime.fromisoformat(trade['entry_time']).strftime('%Y-%m-%d')
            entry_year_month = entry_date[:7]  # YYYY-MM
            current_year_month = f"{year:04d}-{month:02d}"

            if entry_year_month == current_year_month:
                if entry_date not in daily_profit:
                    daily_profit[entry_date] = {'profit': 0, 'count': 0}
                daily_profit[entry_date]['profit'] += trade.get('profit', 0)
                daily_profit[entry_date]['count'] += 1
        except:
            pass

    return jsonify({
        "year": year,
        "month": month,
        "daily_profit": daily_profit
    })

@app.route('/api/trades/<date>', methods=['GET'])
@token_required
def get_trades_by_date(date):
    """특정 날짜의 거래 내역 조회"""
    username = get_current_user() or 'guest'
    trades = load_trades(username)

    date_trades = []
    for trade in trades:
        try:
            entry_date = datetime.fromisoformat(trade['entry_time']).strftime('%Y-%m-%d')
            if entry_date == date:
                date_trades.append(trade)
        except:
            pass

    return jsonify({"date": date, "trades": date_trades})

@app.route('/api/coins/add', methods=['POST'])
@token_required
def add_coin():
    """새 코인 추가"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    try:
        data = request.json
        symbol = data.get('symbol', '').lower()

        if not symbol:
            return jsonify({"success": False, "error": "심볼을 입력해주세요"}), 400

        if symbol in state["coins"]:
            return jsonify({"success": False, "error": "이미 추가된 코인입니다"}), 400

        # 새 코인 추가
        state["coins"].append(symbol)
        state[symbol] = create_default_coin_state(symbol)

        # 파일에 저장
        save_state(state, username)

        logger.info(f"[INFO] 새 코인 추가: {symbol.upper()}, 현재 코인: {state['coins']}")
        return jsonify({"success": True, "message": f"{symbol.upper()} 추가 완료", "coins": state["coins"]})
    except Exception as e:
        logger.error(f"[ERROR] add_coin: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/coins/remove', methods=['POST'])
@token_required
def remove_coin():
    """코인 제거"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    try:
        data = request.json
        symbol = data.get('symbol', '').lower()

        if not symbol:
            return jsonify({"success": False, "error": "심볼을 입력해주세요"}), 400

        if symbol not in state["coins"]:
            return jsonify({"success": False, "error": "존재하지 않는 코인입니다"}), 400

        # 코인 제거
        state["coins"].remove(symbol)
        if symbol in state:
            del state[symbol]

        # 파일에 저장
        save_state(state, username)

        logger.info(f"[INFO] 코인 제거: {symbol.upper()}, 현재 코인: {state['coins']}")
        return jsonify({"success": True, "message": f"{symbol.upper()} 삭제 완료", "coins": state["coins"]})
    except Exception as e:
        logger.error(f"[ERROR] remove_coin: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/user/settings/api', methods=['POST'])
@token_required
def save_user_api_settings():
    """사용자 API 키 저장"""
    try:
        username = get_current_user()
        if not username:
            return jsonify({"success": False, "error": "인증 필요"}), 401

        data = request.get_json()
        api_key = data.get('api_key', '').strip()
        api_secret = data.get('api_secret', '').strip()

        if not api_key or not api_secret:
            return jsonify({"success": False, "error": "API 키와 시크릿을 입력하세요"}), 400

        # 사용자 상태 로드
        user_state = load_state(username)
        user_state['api_key'] = api_key
        user_state['api_secret'] = api_secret
        user_state['mode'] = 'live'

        # 저장
        save_state(user_state, username)

        logger.info(f"[INFO] {username} - API 키 저장, 라이브 모드 전환")
        return jsonify({"success": True, "message": "API 키가 저장되었습니다", "mode": "live"})
    except Exception as e:
        logger.error(f"[ERROR] save_user_api_settings: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/coins/list', methods=['GET'])
@token_required
def get_coins_list():
    """코인 목록 조회"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    return jsonify({"coins": state["coins"]})

@app.route('/api/coins/<coin>/settings', methods=['GET'])
@token_required
def get_coin_settings(coin):
    """코인별 설정 조회"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    coin = coin.lower()

    if coin not in state.get("coins", []):
        return jsonify({"error": "존재하지 않는 코인"}), 400

    # coin_settings에서 설정 조회, 없으면 기본값
    coin_settings = state.get("coin_settings", {})
    settings = coin_settings.get(coin, {})

    return jsonify({
        "initial_seed": settings.get("initial_seed", 1000),
        "current_seed": settings.get("current_seed", settings.get("initial_seed", 1000)),
        "leverage": settings.get("leverage", 10),
        "tp": settings.get("tp", 2.0),
        "sl": settings.get("sl", 1.5),
        "entry_percent": settings.get("entry_percent", 75)
    })

@app.route('/api/coins/<coin>/settings', methods=['POST'])
@token_required
def set_coin_settings(coin):
    """코인별 설정 저장"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    coin = coin.lower()

    if coin not in state.get("coins", []):
        return jsonify({"success": False, "error": "존재하지 않는 코인"}), 400

    try:
        data = request.get_json()

        # coin_settings 구조 초기화
        if "coin_settings" not in state:
            state["coin_settings"] = {}

        # 현재 시드 유지 (첫 설정이면 initial_seed와 동일)
        current_settings = state["coin_settings"].get(coin, {})
        current_seed = current_settings.get("current_seed", data.get("initial_seed", 1000))

        state["coin_settings"][coin] = {
            "initial_seed": data.get("initial_seed", 1000),
            "current_seed": current_seed,
            "leverage": data.get("leverage", 10),
            "tp": data.get("tp", 2.0),
            "sl": data.get("sl", 1.5),
            "entry_percent": data.get("entry_percent", 75)
        }

        # 상태 저장
        save_state(state, username)

        logger.info(f"[INFO] {coin.upper()} 설정 저장: {state['coin_settings'][coin]}")
        return jsonify({"success": True, "message": f"{coin.upper()} 설정이 저장되었습니다"})
    except Exception as e:
        logger.error(f"[ERROR] set_coin_settings ({coin}): {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/trades/calendar', methods=['GET'])
@token_required
def get_trades_calendar():
    """날짜별 거래 통계 (달력용)"""
    username = get_current_user() or 'guest'
    trades = load_trades(username)
    state = load_state(username)

    # 날짜별로 그룹화
    calendar_data = {}

    for trade in trades:
        # exit_time 기준으로 날짜 추출
        exit_time_str = trade.get('exit_time', '')
        if exit_time_str:
            date_str = exit_time_str.split('T')[0]  # YYYY-MM-DD 형식

            if date_str not in calendar_data:
                calendar_data[date_str] = {
                    'date': date_str,
                    'total_trades': 0,
                    'win_trades': 0,
                    'loss_trades': 0,
                    'total_profit': 0,
                    'trades': []
                }

            # 통계 업데이트
            calendar_data[date_str]['total_trades'] += 1
            profit = trade.get('profit', 0)
            calendar_data[date_str]['total_profit'] += profit

            if profit > 0:
                calendar_data[date_str]['win_trades'] += 1
            else:
                calendar_data[date_str]['loss_trades'] += 1

            calendar_data[date_str]['trades'].append(trade)

    return jsonify({
        "success": True,
        "data": calendar_data,
        "total_seed": state.get('total_seed', 0)
    })

@app.route('/api/trades/calendar-detail/<date_str>', methods=['GET'])
@token_required
def get_trades_calendar_detail(date_str):
    """특정 날짜의 거래 내역 (달력용)"""
    username = get_current_user() or 'guest'
    trades = load_trades(username)

    trades_on_date = []
    for trade in trades:
        exit_time_str = trade.get('exit_time', '')
        if exit_time_str:
            trade_date = exit_time_str.split('T')[0]
            if trade_date == date_str:
                trades_on_date.append(trade)

    return jsonify({
        "success": True,
        "date": date_str,
        "trades": trades_on_date
    })

if __name__ == '__main__':
    # 백그라운드 스레드 시작 (상태는 필요할 때 초기화)
    thread = threading.Thread(target=update_prices, daemon=True)
    thread.start()

    # Flask 로그 비활성화 (거래 로그만 표시)
    flask_log = logging.getLogger('werkzeug')
    flask_log.setLevel(logging.ERROR)

    logger.info("[INIT] Bybit Bot 시작 - 사용자 로그인 대기 중")

    # Flask 서버 시작
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
