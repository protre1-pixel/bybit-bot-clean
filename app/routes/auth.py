"""인증 라우트"""
import time
import uuid
import jwt
import logging
from datetime import datetime
from flask import Blueprint, jsonify, request
from app.config import JWT_SECRET, JWT_ALGORITHM
from app.utils import get_current_user, load_state, save_state, get_user_data_dir
from app.services import hash_password, verify_password, load_users, save_users
from app.utils import create_default_coin_state

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


@auth_bp.route('/register', methods=['POST'])
def register():
    """회원가입"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "유효한 JSON 데이터가 필요합니다"}), 400

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

        # 새 사용자의 초기 상태 생성
        initial_state = {
            "mode": "paper",
            "available_coins": [],
            "total_seed": 3000,
            "max_trades": 5,
            "trading_enabled": False
        }
        save_state(initial_state, username)

        logger.info(f"[INFO] 새 사용자 등록: {username}")

        return jsonify({
            "success": True,
            "message": f"{username} 사용자로 가입되었습니다"
        }), 201

    except Exception as e:
        logger.error(f"[ERROR] register: {e}")
        return jsonify({"error": str(e)}), 500


@auth_bp.route('/login', methods=['POST'])
def login():
    """로그인"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "유효한 JSON 데이터가 필요합니다"}), 400

        username = data.get('username', '').strip()
        password = data.get('password', '').strip()

        if not username or not password:
            return jsonify({"error": "사용자명과 비밀번호를 입력해주세요"}), 400

        users = load_users()

        if username not in users:
            return jsonify({"error": "존재하지 않는 사용자명입니다"}), 401

        # 비밀번호 확인
        if not verify_password(password, users[username]["password_hash"]):
            return jsonify({"error": "비밀번호가 일치하지 않습니다"}), 401

        # JWT 토큰 생성
        now = int(time.time())
        payload = {
            'username': username,
            'jti': str(uuid.uuid4()),
            'iat': now,
            'exp': now + (86400 * 7)  # 7일
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        if isinstance(token, bytes):
            token = token.decode('utf-8')

        # 상태 초기화 (사용자별 상태 로드)
        state_data = load_state(username)

        # 상태에 없는 코인들의 데이터만 초기화 (기존 코인 유지!)
        for coin in state_data.get("available_coins", []):
            if coin not in state_data:
                state_data[coin] = create_default_coin_state(coin)

            # 초기 가격 로드
            from app.services import get_current_price
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


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """로그아웃 (JWT는 클라이언트에서 토큰 삭제)"""
    try:
        return jsonify({
            "success": True,
            "message": "로그아웃되었습니다"
        })

    except Exception as e:
        logger.error(f"[ERROR] logout: {e}")
        return jsonify({"error": str(e)}), 500


@auth_bp.route('/check', methods=['GET'])
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
