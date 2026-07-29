"""Bybit 지갑 잔액 조회 및 자금 검증"""
import logging
from app.config import bybit_client

logger = logging.getLogger(__name__)


def get_bybit_balance():
    """Bybit 실제 USDT 잔액 조회"""
    try:
        if not bybit_client:
            logger.error("[ERROR] Bybit 클라이언트 없음")
            return None

        # Spot 지갑 조회
        response = bybit_client.get_wallet_balance(
            accountType="UNIFIED"
        )

        if response['retCode'] != 0:
            logger.error(f"[ERROR] Bybit 잔액 조회 실패: {response}")
            return None

        # USDT 잔액 찾기
        for coin in response['result']['list'][0]['coin']:
            if coin['coin'] == 'USDT':
                balance = float(coin['walletBalance'])
                logger.info(f"[WALLET] Bybit USDT 잔액: ${balance:.2f}")
                return balance

        logger.warning("[WARN] USDT 잔액 없음")
        return 0.0

    except Exception as e:
        logger.error(f"[ERROR] get_bybit_balance: {e}")
        return None


def validate_trading_capital(ui_initial_capital, username=None):
    """UI 초기자본이 실제 자금보다 크면 거래 불가"""
    try:
        bybit_balance = get_bybit_balance()

        if bybit_balance is None:
            return {
                "success": False,
                "error": "Bybit 잔액 조회 실패",
                "bybit_balance": None,
                "ui_capital": ui_initial_capital,
                "is_valid": False
            }

        # 검증: UI 초기자본 ≤ Bybit 실제자금
        is_valid = ui_initial_capital <= bybit_balance

        result = {
            "success": True,
            "bybit_balance": round(bybit_balance, 2),
            "ui_capital": ui_initial_capital,
            "is_valid": is_valid,
            "message": f"Bybit: ${bybit_balance:.2f}, UI: ${ui_initial_capital:.2f}"
        }

        if not is_valid:
            result["error"] = f"❌ UI 초기자본(${ui_initial_capital:.2f})이 실제자금(${bybit_balance:.2f})보다 큽니다!"
            logger.warning(f"[WARN] 자금 부족: UI ${ui_initial_capital} > Bybit ${bybit_balance}")
        else:
            logger.info(f"[OK] 자금 충분: UI ${ui_initial_capital} ≤ Bybit ${bybit_balance}")

        return result

    except Exception as e:
        logger.error(f"[ERROR] validate_trading_capital: {e}")
        return {
            "success": False,
            "error": str(e),
            "is_valid": False
        }
