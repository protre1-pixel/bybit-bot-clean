"""코인 선별 및 캐싱"""
import os
import json
import logging
from datetime import datetime
from app import config

logger = logging.getLogger(__name__)

# 2026-08-09: Bybit linear 카테고리에 토큰화 주식(stock)/원자재(commodity)가
# 실제 암호화폐와 섞여 있음을 확인 (예: SNDK, TSLA, NVDA, GME, XAU 등 178개).
# 이런 종목은 실물 시장(주식장 시간, 배당/실적 이벤트 등)의 영향을 받아
# 우리 전략(암호화폐 변동성 기반 스퀴즈 브레이크아웃)과 성격이 다르므로 선별에서 제외.
# innovation(신규 상장 소형 알트코인)은 실제 암호화폐이므로 제외하지 않음.
_STOCK_EXCLUSION_TYPES = {"stock", "commodity"}
_stock_exclusion_cache = {"symbols": None, "timestamp": 0}
STOCK_EXCLUSION_CACHE_SEC = 3600  # 1시간 캐시 (종목 목록은 자주 안 바뀜)


def get_stock_excluded_symbols():
    """Bybit linear 심볼 중 토큰화 주식/원자재(symbolType) 목록 조회 (1시간 캐시)"""
    now = datetime.now().timestamp()
    if (_stock_exclusion_cache["symbols"] is not None and
            now - _stock_exclusion_cache["timestamp"] < STOCK_EXCLUSION_CACHE_SEC):
        return _stock_exclusion_cache["symbols"]

    excluded_symbols = set()
    try:
        if not config.bybit_client:
            return excluded_symbols

        cursor = None
        while True:
            params = {"category": "linear", "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            resp = config.bybit_client.get_instruments_info(**params)
            if resp['retCode'] != 0:
                logger.error(f"[ERROR] get_instruments_info 실패: {resp}")
                break
            for info in resp['result']['list']:
                if info.get('symbolType') in _STOCK_EXCLUSION_TYPES:
                    excluded_symbols.add(info['symbol'])
            cursor = resp['result'].get('nextPageCursor')
            if not cursor:
                break

        _stock_exclusion_cache["symbols"] = excluded_symbols
        _stock_exclusion_cache["timestamp"] = now
        logger.info(f"[INFO] 주식/원자재 토큰 제외 목록 갱신: {len(excluded_symbols)}개")
    except Exception as e:
        logger.error(f"[ERROR] get_stock_excluded_symbols: {e}")
        # 실패 시 이전 캐시가 있으면 그대로 사용, 없으면 빈 set (제외 없이 진행)
        if _stock_exclusion_cache["symbols"] is not None:
            return _stock_exclusion_cache["symbols"]

    return excluded_symbols


# 2026-08-09: turnover24h(24시간 누적 거래대금)만으로는 "지금 이 순간 실제
# 체결 가능한 물량"을 반영 못 함이 확인됨 - CYS/TUT(Bybit ST 경고 라벨 붙은
# 저유동성 코인)와 BLESS/BEAT/BLUAI가 거래대금 순위는 상위권인데 실제 호가창
# 최우선호가 규모는 BTC 대비 1,000~10,000배 얇았음 (오늘 ACE -$177, GWEI -$52
# 손실 코인도 동일하게 호가창이 매우 얇았음 - 진입/청산시 슬리피지가 커지고
# 신호 자체가 얇은 호가창 노이즈로 오작동하기 쉬움).
# Bybit의 ST(Special Treatment) 경고 기준(편측 유동성 $1,000~5,000, 스프레드
# 0.5~1.5%)을 참고해 최소 유동성 문턱을 두고, 이 밑이면 후보에서 제외.
MIN_ORDERBOOK_NOTIONAL_USD = 1500  # 상위 5호가 누적 매수/매도 양쪽 다 이 이상이어야 통과
MAX_SPREAD_PCT = 0.5               # 최우선매수-매도 스프레드가 이보다 넓으면 제외


def check_orderbook_liquidity(symbol):
    """호가창 상위 5호가 누적 매수/매도 규모(USD 환산)와 스프레드로 실질 유동성 체크.
    거래대금(turnover24h) 순위만으로는 못 잡아내는 "겉만 큰" 저유동성 코인을
    걸러내기 위함. 조회 실패시 안전하게 제외(False).

    2026-08-09: 최우선호가(1호가)만 보면 BNB/LINK/DOT/ATOM/UNI/NEAR 등 실제로는
    유동성이 충분한 메이저 코인까지 오탐으로 제외되는 문제 발견 - 마켓메이커가
    최우선가에는 소량만 걸어두고 빠르게 갱신하는 코인이 많아 1호가 스냅샷만으로는
    "체결 가능한 실제 물량"을 못 잡아냄. 상위 5호가 누적으로 바꿔서 슬리피지 없이
    실제로 체결 가능한 물량을 반영하도록 수정. (ATOM 실측 ~$2,200 vs GWEI 실측
    ~$1,350 - 그 사이인 $1,500을 문턱으로 사용)"""
    try:
        if not config.bybit_client:
            return False

        resp = config.bybit_client.get_orderbook(category="linear", symbol=symbol, limit=5)
        if resp['retCode'] != 0:
            return False

        asks = resp['result'].get('a', [])
        bids = resp['result'].get('b', [])
        if not asks or not bids:
            return False

        ask_px = float(asks[0][0])
        bid_px = float(bids[0][0])
        if bid_px <= 0 or ask_px <= 0:
            return False

        ask_notional = sum(float(p) * float(q) for p, q in asks)
        bid_notional = sum(float(p) * float(q) for p, q in bids)
        spread_pct = (ask_px - bid_px) / bid_px * 100

        if ask_notional < MIN_ORDERBOOK_NOTIONAL_USD or bid_notional < MIN_ORDERBOOK_NOTIONAL_USD:
            return False
        if spread_pct > MAX_SPREAD_PCT:
            return False

        return True
    except Exception as e:
        logger.debug(f"[DEBUG] 호가창 유동성 체크 실패: {symbol} - {e}")
        return False


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
    """거래량 기준 상위 10개 코인 선별 (Bybit)"""
    try:
        if not config.bybit_client:
            logger.warning("[WARN] Bybit 미연결 - 기본 코인 반환")
            return ["sol", "doge", "ada", "avax", "link", "matic", "shib", "ape", "sui", "inj"]

        response = config.bybit_client.get_tickers(category="linear", limit=50)

        if response['retCode'] != 0 or not response['result']['list']:
            logger.error(f"[ERROR] Bybit 코인 조회 실패: {response}")
            return []

        # 거래량 기준으로 정렬
        coins_data = response['result']['list']
        coins_data = sorted(coins_data, key=lambda x: float(x.get('turnover24h', 0)), reverse=True)

        # 제외할 스테이블 코인만
        excluded = ['USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'FDUSD']
        stock_excluded = get_stock_excluded_symbols()

        # 상위 10개 선별 (USDT 쌍만, 호가창 유동성 체크 통과한 것만)
        top_coins = []
        for coin_info in coins_data:
            if len(top_coins) >= 10:
                break
            symbol = coin_info['symbol']
            if symbol in stock_excluded:
                continue
            if not symbol.endswith('USDT'):
                continue
            coin_name = symbol.replace('USDT', '').lower()
            if coin_name.upper() in excluded:
                continue
            if not check_orderbook_liquidity(symbol):
                logger.info(f"[INFO] {coin_name.upper()}: 호가창 유동성 부족으로 제외")
                continue
            top_coins.append(coin_name)

        top_coins = top_coins[:10]
        save_cached_coins(top_coins)
        return top_coins

    except Exception as e:
        logger.error(f"[ERROR] get_top_coins_by_volume: {e}")
        return []


def get_top_coins_by_hma_strength():
    """HMA 신호 강도 기준 상위 10개 코인 선별 (LONG/SHORT 상관없이)"""
    try:
        if not config.bybit_client:
            logger.warning("[WARN] Bybit 미연결 - 기본 코인 반환")
            return ["btc", "eth", "wld", "near", "sol", "ada", "link", "matic", "avax", "doge"]

        response = config.bybit_client.get_tickers(category="linear", limit=100)

        if response['retCode'] != 0 or not response['result']['list']:
            logger.error(f"[ERROR] Bybit 코인 조회 실패: {response}")
            return []

        from app.services.price_service import calculate_hma

        excluded = ['USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'FDUSD']
        stock_excluded = get_stock_excluded_symbols()
        coin_scores = []

        # 각 코인의 HMA 신호 강도 계산
        for coin_info in response['result']['list']:
            symbol = coin_info['symbol']
            if not symbol.endswith('USDT'):
                continue
            if symbol in stock_excluded:
                continue

            coin_name = symbol.replace('USDT', '').lower()
            if coin_name.upper() in excluded:
                continue

            try:
                # HMA 계산
                hma60 = calculate_hma(coin_name, period=60, timeframe=60)
                hma200 = calculate_hma(coin_name, period=200, timeframe=60)

                if hma60 is None or hma200 is None:
                    continue

                # 신호 강도 = 절댓값 (LONG/SHORT 구분 없음)
                signal_strength = abs(hma60 - hma200) / hma200 * 100

                coin_scores.append({
                    'coin': coin_name,
                    'strength': signal_strength,
                    'hma60': hma60,
                    'hma200': hma200
                })
            except Exception as e:
                logger.debug(f"[DEBUG] {coin_name} HMA 계산 실패: {e}")
                continue

        # 신호 강도 높은 순으로 정렬
        coin_scores.sort(key=lambda x: x['strength'], reverse=True)

        # 상위 10개 (호가창 유동성 체크 통과한 것만)
        top_coins = []
        for c in coin_scores:
            if len(top_coins) >= 10:
                break
            symbol = c['coin'].upper() + 'USDT'
            if not check_orderbook_liquidity(symbol):
                logger.info(f"[INFO] {c['coin'].upper()}: 호가창 유동성 부족으로 제외")
                continue
            top_coins.append(c['coin'])

        logger.info(f"[INFO] HMA 신호 강도로 선별: {top_coins}")
        return top_coins

    except Exception as e:
        logger.error(f"[ERROR] get_top_coins_by_hma_strength: {e}")
        return []


def get_top_coins_by_volume_volatility():
    """거래량 + 변동성 조합으로 상위 10개 코인 선별"""
    try:
        if not config.bybit_client:
            logger.warning("[WARN] Bybit 미연결 - 기본 코인 반환")
            return ["btc", "eth", "wld", "near", "sol", "ada", "link", "matic", "avax", "doge"]

        response = config.bybit_client.get_tickers(category="linear", limit=50)

        if response['retCode'] != 0 or not response['result']['list']:
            logger.error(f"[ERROR] Bybit 코인 조회 실패: {response}")
            return []

        excluded = ['USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'FDUSD']
        stock_excluded = get_stock_excluded_symbols()
        coin_scores = []

        # 각 코인의 거래량 + 변동성 점수 계산
        for coin_info in response['result']['list']:
            symbol = coin_info['symbol']
            if not symbol.endswith('USDT'):
                continue
            if symbol in stock_excluded:
                continue

            coin_name = symbol.replace('USDT', '').lower()
            if coin_name.upper() in excluded:
                continue

            try:
                # 거래량 (24시간)
                turnover24h = float(coin_info.get('turnover24h', 0))

                # 변동성 (고가 - 저가) / 현재가
                high24h = float(coin_info.get('highPrice24h', 0))
                low24h = float(coin_info.get('lowPrice24h', 0))
                close = float(coin_info.get('lastPrice', 0))

                if close == 0:
                    continue

                volatility = ((high24h - low24h) / close * 100) if high24h > 0 else 0

                # 정규화: 거래량 순위와 변동성을 0-100 범위로
                # 최종 점수 = 거래량 50% + 변동성 50%
                coin_scores.append({
                    'coin': coin_name,
                    'turnover': turnover24h,
                    'volatility': volatility,
                    'combined_score': (turnover24h / 1_000_000) + volatility  # 거래량을 백만 단위로 정규화
                })
            except Exception as e:
                logger.debug(f"[DEBUG] {coin_name} 점수 계산 실패: {e}")
                continue

        # 최종 점수 높은 순으로 정렬
        coin_scores.sort(key=lambda x: x['combined_score'], reverse=True)

        # 상위 10개 (호가창 유동성 체크 통과한 것만)
        top_coins = []
        for c in coin_scores:
            if len(top_coins) >= 10:
                break
            symbol = c['coin'].upper() + 'USDT'
            if not check_orderbook_liquidity(symbol):
                logger.info(f"[INFO] {c['coin'].upper()}: 호가창 유동성 부족으로 제외")
                continue
            top_coins.append(c['coin'])

        logger.info(f"[INFO] 거래량+변동성으로 선별: {top_coins}")
        save_cached_coins(top_coins)  # ← 캐시 저장!
        return top_coins

    except Exception as e:
        logger.error(f"[ERROR] get_top_coins_by_volume_volatility: {e}")
        return []
