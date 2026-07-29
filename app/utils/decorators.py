"""JWT 토큰 검증 데코레이터"""
from functools import wraps
from flask import jsonify, request
import jwt
from app.config import JWT_SECRET, JWT_ALGORITHM


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
