"""상태 및 거래 기록 관리"""
import os
import json
import threading
import logging
from filelock import FileLock
from flask import request
import jwt
from app.config import JWT_SECRET, JWT_ALGORITHM

logger = logging.getLogger(__name__)

# 전역 Lock 객체 (스레드 안전성)
_state_lock = threading.RLock()
_file_locks = {}

# 기본 상태
DEFAULT_STATE = {
    "mode": "paper",
    "coins": [],
    "total_seed": 3000,
    "trading_enabled": False,
    "coin_settings": {}
}


def get_current_user():
    """현재 로그인한 사용자 반환 (JWT 토큰 기반)"""
    try:
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return None

        token = auth_header.split(' ')[1]
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get('username')
    except (jwt.InvalidTokenError, jwt.ExpiredSignatureError, IndexError, AttributeError):
        return None


def get_user_data_dir(username):
    """사용자 데이터 디렉토리 경로"""
    from app.config import USERS_DIR
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
