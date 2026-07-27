"""Bybit 주문 관리"""
import logging
from app.config import bybit_client

logger = logging.getLogger(__name__)


def place_buy_order(symbol, qty, order_type="Market", mode="paper"):
    """매수 주문"""
    try:
        if mode == "paper":
            logger.info(f"[PAPER] 매수 신호: {symbol} × {qty} (주문 안 넣음)")
            return {"success": True, "mode": "paper", "symbol": symbol, "qty": qty}

        if not bybit_client:
            logger.error("[ERROR] Bybit 클라이언트 없음")
            return {"success": False, "error": "Bybit 클라이언트 없음"}

        response = bybit_client.place_order(
            category="spot",
            symbol=symbol,
            side="Buy",
            orderType=order_type,
            qty=str(qty)
        )

        if response['retCode'] != 0:
            logger.error(f"[ERROR] 매수 주문 실패: {response}")
            return {"success": False, "error": response.get('retMsg')}

        order_id = response['result']['orderId']
        logger.info(f"[BUY] 매수 주문 성공: {symbol} × {qty}, 주문ID: {order_id}")
        return {
            "success": True,
            "order_id": order_id,
            "symbol": symbol,
            "qty": qty,
            "side": "Buy"
        }

    except Exception as e:
        logger.error(f"[ERROR] place_buy_order: {e}")
        return {"success": False, "error": str(e)}


def place_sell_order(symbol, qty, order_type="Market", mode="paper"):
    """매도 주문"""
    try:
        if mode == "paper":
            logger.info(f"[PAPER] 매도 신호: {symbol} × {qty} (주문 안 넣음)")
            return {"success": True, "mode": "paper", "symbol": symbol, "qty": qty}

        if not bybit_client:
            logger.error("[ERROR] Bybit 클라이언트 없음")
            return {"success": False, "error": "Bybit 클라이언트 없음"}

        response = bybit_client.place_order(
            category="spot",
            symbol=symbol,
            side="Sell",
            orderType=order_type,
            qty=str(qty)
        )

        if response['retCode'] != 0:
            logger.error(f"[ERROR] 매도 주문 실패: {response}")
            return {"success": False, "error": response.get('retMsg')}

        order_id = response['result']['orderId']
        logger.info(f"[SELL] 매도 주문 성공: {symbol} × {qty}, 주문ID: {order_id}")
        return {
            "success": True,
            "order_id": order_id,
            "symbol": symbol,
            "qty": qty,
            "side": "Sell"
        }

    except Exception as e:
        logger.error(f"[ERROR] place_sell_order: {e}")
        return {"success": False, "error": str(e)}


def cancel_order(symbol, order_id, mode="paper"):
    """주문 취소"""
    try:
        if mode == "paper":
            logger.info(f"[PAPER] 주문 취소: {symbol} {order_id} (취소 안 함)")
            return {"success": True, "mode": "paper"}

        if not bybit_client:
            logger.error("[ERROR] Bybit 클라이언트 없음")
            return {"success": False, "error": "Bybit 클라이언트 없음"}

        response = bybit_client.cancel_order(
            category="spot",
            symbol=symbol,
            orderId=order_id
        )

        if response['retCode'] != 0:
            logger.error(f"[ERROR] 주문 취소 실패: {response}")
            return {"success": False, "error": response.get('retMsg')}

        logger.info(f"[CANCEL] 주문 취소 성공: {symbol} {order_id}")
        return {"success": True, "order_id": order_id}

    except Exception as e:
        logger.error(f"[ERROR] cancel_order: {e}")
        return {"success": False, "error": str(e)}
