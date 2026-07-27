"""코인 선별 및 캐싱"""
import os
import json
import logging
from datetime import datetime
from app.config import bybit_client

logger = logging.getLogger(__name__)


def load_cached_coins():
    """캐시된 선별 코인 로드 (정각 00:00 기준 리셋)"""
    cache_file = os.path.join(os.path.dirname(__file__), "..", "..", "selected_coins_cache.json")
    try:
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                data = json.load(f)

            # 캐시 생성 날짜와 현재 날짜 비교
            cache_timestamp = data.get("timestamp", 0)
            cache_date = datetime.fromtimestamp(cache_timestamp).date()
            current_date = datetime.now().date()

            # 같은 날짜면 캐시 사용 (정각 기준)
            if cache_date == current_date:
                logger.info(f"[INFO] 캐시된 코인 사용 ({len(data.get('coins', []))}개) - 오늘 선별")
                return data.get("coins", [])
            else:
                logger.info(f"[INFO] 캐시 만료 (어제: {cache_date}, 오늘: {current_date}) - 재선별 필요")
    except Exception as e:
        logger.error(f"[ERROR] 캐시 파일 로드 실패: {e}")

    return None  # 캐시 없음, 재선별 필요


def save_cached_coins(coins):
    """선별된 코인을 파일에 캐시"""
    cache_file = os.path.join(os.path.dirname(__file__), "..", "..", "selected_coins_cache.json")
    try:
        data = {
            "coins": coins,
            "timestamp": datetime.now().timestamp()
        }
        with open(cache_file, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"[INFO] 선별 코인 캐시 저장 ({len(coins)}개): {coins}")
    except Exception as e:
        logger.error(f"[ERROR] 캐시 저장 실패: {e}")


def get_top_coins_by_volume():
    """유동성 + 거래량 기준 상위 10개 코인 선별 (Bybit)"""
    try:
        if not bybit_client:
            logger.warning("[WARN] Bybit 미연결 - 기본 코인 반환")
            return ["sol", "doge", "ada", "avax", "link", "matic", "shib", "ape", "sui", "inj", "floki"]

        response = bybit_client.get_tickers(category="spot", limit=50)

        if response['retCode'] != 0 or not response['result']['list']:
            logger.error(f"[ERROR] Bybit 코인 조회 실패: {response}")
            return []

        # 거래량 기준으로 정렬
        coins_data = response['result']['list']
        coins_data = sorted(coins_data, key=lambda x: float(x.get('turnover24h', 0)), reverse=True)

        # 제외할 대형/스테이블 코인
        excluded = ['BTC', 'ETH', 'BNB', 'XRP', 'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'FDUSD']

        # 상위 10개 선별 (USDT 쌍만)
        top_coins = []
        for coin_info in coins_data:
            symbol = coin_info['symbol']
            if symbol.endswith('USDT') and len(top_coins) < 10:
                coin_name = symbol.replace('USDT', '').lower()
                if coin_name.upper() not in excluded:
                    top_coins.append(coin_name)

        top_coins = top_coins[:10]
        save_cached_coins(top_coins)  # 파일에 캐시 저장
        return top_coins

    except Exception as e:
        logger.error(f"[ERROR] get_top_coins_by_volume: {e}")
        return []
