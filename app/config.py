import os
from dotenv import load_dotenv
from pybit.unified_trading import HTTP
import logging

logger = logging.getLogger(__name__)

# secrets.env 로드
secrets_paths = [
    'C:\\Users\\protre\\codex-secrets\\secrets.env',
    '/home/protre/codex-secrets/secrets.env',
    '.env'
]
for secrets_path in secrets_paths:
    if os.path.exists(secrets_path):
        load_dotenv(secrets_path)
        logger.info(f"[INIT] Loaded secrets from: {secrets_path}")
        break

# JWT 설정
JWT_SECRET = os.getenv('JWT_SECRET', 'bybit-bot-jwt-secret-2026-fallback')
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION = 86400 * 7  # 7일

if JWT_SECRET == 'bybit-bot-jwt-secret-2026-fallback':
    logger.warning("[WARN] JWT_SECRET가 설정되지 않았습니다. 환경변수 JWT_SECRET을 설정하세요.")

# Bybit API 초기화
BYBIT_API_KEY = os.getenv('key')
BYBIT_API_SECRET = os.getenv('secret')

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

# 디렉토리 설정
USERS_DIR = "users"
USERS_FILE = "users.json"
USERS_LOCK_FILE = "users.json.lock"

os.makedirs(USERS_DIR, exist_ok=True)
