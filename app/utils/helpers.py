"""유틸리티 헬퍼 함수들"""
import os
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def create_default_coin_state(coin_name, margin=1000):
    """새 코인의 기본 상태 생성"""
    return {
        "position": None,
        "entry_price": None,
        "entry_time": None,
        "current_price": 0,
        "margin": margin,
        "leverage": 10,
        "position_size": 0,
        "profit": 0,
        "profit_pct": 0,
        "max_profit_price": None,
        "min_profit_price": None,
        "sl_price": None,
        "tp_price": None,
        "timeframe": 60,
        "position_ratio": 75,
        "tp": 2.0,
        "sl": 1.5,
        "last_close_time": None
    }


def format_price(price, coin=None):
    """Bybit API에서 받은 가격을 그대로 사용 (소수점 제한 없음)"""
    if price is None:
        return 0.0
    return float(price)
