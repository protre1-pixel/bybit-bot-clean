"""라우트 모듈"""
from .auth import auth_bp
from .dashboard import dashboard_bp
from .trading import trading_bp
from .coins import coins_bp
from .settings import settings_bp

__all__ = [
    'auth_bp',
    'dashboard_bp',
    'trading_bp',
    'coins_bp',
    'settings_bp'
]
