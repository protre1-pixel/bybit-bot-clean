import os
from dotenv import load_dotenv
from pybit.unified_trading import HTTP
import logging

logger = logging.getLogger(__name__)

# secrets.env 로드 (프로젝트 로컬 파일 우선, 없는 값은 전역 파일에서 보충)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
secrets_paths = [
    os.path.join(PROJECT_ROOT, 'secrets.env'),
    'C:\\Users\\protre\\codex-secrets\\secrets.env',
    '/home/protre/codex-secrets/secrets.env',
    '.env'
]
for secrets_path in secrets_paths:
    if os.path.exists(secrets_path):
        load_dotenv(secrets_path, override=False)
        logger.info(f"[INIT] Loaded secrets from: {secrets_path}")

# JWT 설정
JWT_SECRET = os.getenv('JWT_SECRET')
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION = 86400 * 7  # 7일

if not JWT_SECRET:
    raise RuntimeError("[FATAL] JWT_SECRET 환경변수가 설정되지 않았습니다. secrets.env에 JWT_SECRET을 추가하세요.")

# Bybit API 초기화
# - 데모 트레이딩(BYBIT_DEMO=true): BYBIT_DEMO_API_KEY/SECRET 사용, api-demo.bybit.com 로 연결
#   (2026년 기준 Bybit이 구 testnet.bybit.com을 없애고 본계정 안의 Demo Trading으로 통합함.
#    데모용 API 키는 반드시 Demo Trading 화면 안에서 별도로 발급받아야 함 - 실계좌 키와 다름)
# - 실전(기본값): 프로젝트 secrets.env는 BYBIT_API_KEY/BYBIT_API_SECRET, 전역 파일은 key/secret 사용
BYBIT_DEMO = os.getenv('BYBIT_DEMO', 'false').lower() in ('1', 'true', 'yes')

if BYBIT_DEMO:
    BYBIT_API_KEY = os.getenv('BYBIT_DEMO_API_KEY')
    BYBIT_API_SECRET = os.getenv('BYBIT_DEMO_API_SECRET')
else:
    BYBIT_API_KEY = os.getenv('BYBIT_API_KEY') or os.getenv('key')
    BYBIT_API_SECRET = os.getenv('BYBIT_API_SECRET') or os.getenv('secret')

bybit_client = None
if BYBIT_API_KEY and BYBIT_API_SECRET:
    try:
        bybit_client = HTTP(
            testnet=False,
            demo=BYBIT_DEMO,
            api_key=BYBIT_API_KEY,
            api_secret=BYBIT_API_SECRET
        )
        logger.info(f"[INIT] Bybit API 연결 성공 ({'DEMO' if BYBIT_DEMO else 'LIVE'})")
    except Exception as e:
        logger.error(f"[ERROR] Bybit API 연결 실패: {e}")
        bybit_client = None
else:
    if BYBIT_DEMO:
        logger.warning("[WARN] BYBIT_DEMO=true인데 BYBIT_DEMO_API_KEY/SECRET 없음 - Paper Trade 모드로 실행 중")
    else:
        logger.warning("[WARN] Bybit API 키 없음 - Paper Trade 모드로 실행 중")

# 디렉토리 설정
USERS_DIR = "users"
USERS_FILE = "users.json"
USERS_LOCK_FILE = "users.json.lock"

os.makedirs(USERS_DIR, exist_ok=True)
