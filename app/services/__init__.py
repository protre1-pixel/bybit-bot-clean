"""서비스 모듈"""
from .auth_service import hash_password, verify_password, load_users, save_users
from .coin_service import get_top_coins_by_volume, get_top_coins_by_volume_volatility, load_cached_coins, save_cached_coins
from .price_service import (
    get_current_price,
    calculate_atr,
    calculate_sma,
    update_prices
)
from .trading_service import check_entry_signal, auto_trade, close_trade

__all__ = [
    'hash_password',
    'verify_password',
    'load_users',
    'save_users',
    'get_top_coins_by_volume',
    'get_top_coins_by_volume_volatility',
    'load_cached_coins',
    'save_cached_coins',
    'get_current_price',
    'calculate_atr',
    'calculate_sma',
    'update_prices',
    'check_entry_signal',
    'auto_trade',
    'close_trade'
]
