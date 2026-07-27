"""인증 관련 서비스"""
import os
import json
import logging
import bcrypt
from filelock import FileLock
from app.config import USERS_FILE, USERS_LOCK_FILE

logger = logging.getLogger(__name__)


def hash_password(password):
    """비밀번호 해싱 (bcrypt 사용)"""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')


def verify_password(password, password_hash):
    """비밀번호 검증 (bcrypt 사용)"""
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))


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
