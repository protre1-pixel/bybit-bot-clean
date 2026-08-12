"""Bybit 주문 관리"""
import math
import time
import logging
from app import config

logger = logging.getLogger(__name__)

_lot_size_cache = {}
_price_filter_cache = {}


def _get_lot_size_filter(symbol):
    """심볼의 최소 주문 단위(qtyStep, minOrderQty) 조회 (캐싱)"""
    if symbol in _lot_size_cache:
        return _lot_size_cache[symbol]
    try:
        response = config.bybit_client.get_instruments_info(category="linear", symbol=symbol)
        if response['retCode'] != 0 or not response['result']['list']:
            logger.error(f"[ERROR] instruments info 조회 실패: {symbol} - {response}")
            return None

        lot_filter = response['result']['list'][0]['lotSizeFilter']
        result = {
            "qty_step": float(lot_filter['qtyStep']),
            "min_qty": float(lot_filter['minOrderQty'])
        }
        _lot_size_cache[symbol] = result
        return result
    except Exception as e:
        logger.error(f"[ERROR] _get_lot_size_filter: {symbol} - {e}")
        return None


def round_qty_to_step(symbol, qty):
    """주문 수량을 심볼의 qtyStep 단위로 내림 처리 (최소 수량 미만이면 0 반환)"""
    lot = _get_lot_size_filter(symbol)
    if not lot or lot["qty_step"] <= 0:
        return qty

    qty_step = lot["qty_step"]
    steps = math.floor(qty / qty_step + 1e-9)
    rounded = steps * qty_step

    decimals = max(0, -math.floor(math.log10(qty_step))) if qty_step < 1 else 0
    rounded = round(rounded, decimals)

    if rounded < lot["min_qty"]:
        logger.warning(f"[WARN] {symbol} 주문 수량({rounded})이 최소 단위({lot['min_qty']}) 미만")
        return 0

    return rounded


def _get_price_tick(symbol):
    """심볼의 가격 최소 단위(tickSize) 조회 (캐싱)"""
    if symbol in _price_filter_cache:
        return _price_filter_cache[symbol]
    try:
        response = config.bybit_client.get_instruments_info(category="linear", symbol=symbol)
        if response['retCode'] != 0 or not response['result']['list']:
            logger.error(f"[ERROR] price filter 조회 실패: {symbol} - {response}")
            return None
        tick_size = float(response['result']['list'][0]['priceFilter']['tickSize'])
        _price_filter_cache[symbol] = tick_size
        return tick_size
    except Exception as e:
        logger.error(f"[ERROR] _get_price_tick: {symbol} - {e}")
        return None


def round_price_to_tick(symbol, price):
    """가격을 심볼의 tickSize 단위로 반올림 (거래소가 요구하는 정밀도에 맞춤)"""
    tick = _get_price_tick(symbol)
    if not tick or tick <= 0:
        return price

    steps = round(price / tick)
    rounded = steps * tick

    decimals = max(0, -math.floor(math.log10(tick))) if tick < 1 else 0
    return round(rounded, decimals)


def _extract_fill(o):
    status = o.get("orderStatus")
    avg_price = float(o.get("avgPrice") or 0)
    if status == "Filled" and avg_price > 0:
        return {
            "avg_price": avg_price,
            "fee": float(o.get("cumExecFee") or 0),
            "qty": float(o.get("cumExecQty") or 0),
            "status": status,
        }
    return None


def get_fill_price(symbol, order_id, mode="paper", max_retries=15, delay=0.4):
    """주문 체결 후 실제 평균 체결가/수수료 조회 (라이브 전용)
    get_open_orders는 최근 체결/취소된 주문도 거의 실시간으로 반영해서 우선 사용하고,
    (실측: ~0.1초 내 반영) 혹시 못 찾으면 get_order_history로 재시도(최대 몇 초 지연될 수 있음).
    """
    if mode == "paper" or not order_id:
        return None
    if not config.bybit_client:
        return None

    for attempt in range(max_retries):
        try:
            resp = config.bybit_client.get_open_orders(category="linear", symbol=symbol, orderId=order_id)
            orders = resp.get("result", {}).get("list", [])
            if orders:
                status = orders[0].get("orderStatus")
                fill = _extract_fill(orders[0])
                if fill:
                    return fill
                if status in ("Cancelled", "Rejected"):
                    logger.error(f"[ERROR] {symbol} 주문({order_id}) 체결 실패: {status}")
                    return None

            # open_orders에 없으면 history에서도 확인 (지연 반영 대비 폴백)
            resp = config.bybit_client.get_order_history(category="linear", symbol=symbol, orderId=order_id)
            orders = resp.get("result", {}).get("list", [])
            if orders:
                status = orders[0].get("orderStatus")
                fill = _extract_fill(orders[0])
                if fill:
                    return fill
                if status in ("Cancelled", "Rejected"):
                    logger.error(f"[ERROR] {symbol} 주문({order_id}) 체결 실패: {status}")
                    return None
        except Exception as e:
            logger.warning(f"[WARN] get_fill_price 조회 실패 ({symbol}, 시도 {attempt + 1}/{max_retries}): {e}")
        time.sleep(delay)

    logger.error(f"[ERROR] {symbol} 주문({order_id}) 체결가 조회 타임아웃 - 폴백 가격 사용")
    return None


def set_exchange_stop_loss(symbol, sl_price, mode="paper"):
    """거래소에 실제 SL(Stop Loss)을 설정/갱신.
    봇이 다운되거나 응답이 지연돼도 거래소 서버가 마지막으로 설정된 SL을
    자체적으로 실행해주는 최후의 안전망 역할.
    """
    try:
        if mode == "paper":
            return {"success": True, "mode": "paper"}
        if not config.bybit_client:
            return {"success": False, "error": "Bybit 클라이언트 없음"}

        rounded_sl = round_price_to_tick(symbol, sl_price)

        try:
            response = config.bybit_client.set_trading_stop(
                category="linear",
                symbol=symbol,
                stopLoss=str(rounded_sl),
                positionIdx=0
            )
        except Exception as api_err:
            # pybit는 retCode!=0이면 값을 돌려주는 대신 예외를 던짐.
            # 34040 = "not modified" (이미 동일한 값으로 설정됨) - 정상 케이스이므로 예외로 와도 성공 처리
            status_code = getattr(api_err, 'status_code', None)
            if status_code == 34040:
                logger.debug(f"[SL-SYNC] {symbol} 거래소 SL 이미 ${rounded_sl}로 설정됨 (변경 없음)")
                return {"success": True, "symbol": symbol, "sl_price": rounded_sl}
            raise

        if response['retCode'] not in (0, 34040):  # 34040 = "not modified" (동일 값 재설정)
            logger.error(f"[ERROR] {symbol} 거래소 SL 설정 실패: {response}")
            return {"success": False, "error": response.get('retMsg')}

        logger.debug(f"[SL-SYNC] {symbol} 거래소 SL → ${rounded_sl}")
        return {"success": True, "symbol": symbol, "sl_price": rounded_sl}

    except Exception as e:
        logger.error(f"[ERROR] set_exchange_stop_loss: {symbol} - {e}")
        return {"success": False, "error": str(e)}


def set_leverage(symbol, leverage, mode="paper"):
    """심볼 레버리지를 거래소에 실제로 설정 (진입 주문 직전에 호출)"""
    try:
        if mode == "paper":
            return {"success": True, "mode": "paper"}

        if not config.bybit_client:
            logger.error("[ERROR] Bybit 클라이언트 없음")
            return {"success": False, "error": "Bybit 클라이언트 없음"}

        try:
            response = config.bybit_client.set_leverage(
                category="linear",
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage)
            )
        except Exception as api_err:
            # pybit는 retCode!=0이면 값을 돌려주는 대신 예외를 던짐.
            # 110043 = "leverage not modified" (이미 동일한 값으로 설정됨) - 정상 케이스이므로 예외로 와도 성공 처리
            status_code = getattr(api_err, 'status_code', None)
            if status_code == 110043:
                return {"success": True, "symbol": symbol, "leverage": leverage}
            raise

        # retCode 110043 = "leverage not modified" (이미 동일한 값으로 설정됨) → 정상 처리
        if response['retCode'] not in (0, 110043):
            logger.error(f"[ERROR] 레버리지 설정 실패: {symbol} {leverage}x - {response}")
            return {"success": False, "error": response.get('retMsg')}

        return {"success": True, "symbol": symbol, "leverage": leverage}

    except Exception as e:
        logger.error(f"[ERROR] set_leverage: {symbol} {leverage}x - {e}")
        return {"success": False, "error": str(e)}


def place_buy_order(symbol, qty, order_type="Market", mode="paper", reduce_only=False):
    """매수 주문"""
    try:
        if mode == "paper":
            logger.info(f"[PAPER] 매수 신호: {symbol} × {qty} (주문 안 넣음)")
            return {"success": True, "mode": "paper", "symbol": symbol, "qty": qty}

        if not config.bybit_client:
            logger.error("[ERROR] Bybit 클라이언트 없음")
            return {"success": False, "error": "Bybit 클라이언트 없음"}

        qty = round_qty_to_step(symbol, qty)
        if qty <= 0:
            logger.error(f"[ERROR] {symbol} 주문 수량이 최소 단위 미만")
            return {"success": False, "error": "주문 수량이 최소 단위 미만"}

        response = config.bybit_client.place_order(
            category="linear",
            symbol=symbol,
            side="Buy",
            orderType=order_type,
            qty=str(qty),
            reduceOnly=reduce_only
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


def place_sell_order(symbol, qty, order_type="Market", mode="paper", reduce_only=False):
    """매도 주문"""
    try:
        if mode == "paper":
            logger.info(f"[PAPER] 매도 신호: {symbol} × {qty} (주문 안 넣음)")
            return {"success": True, "mode": "paper", "symbol": symbol, "qty": qty}

        if not config.bybit_client:
            logger.error("[ERROR] Bybit 클라이언트 없음")
            return {"success": False, "error": "Bybit 클라이언트 없음"}

        qty = round_qty_to_step(symbol, qty)
        if qty <= 0:
            logger.error(f"[ERROR] {symbol} 주문 수량이 최소 단위 미만")
            return {"success": False, "error": "주문 수량이 최소 단위 미만"}

        response = config.bybit_client.place_order(
            category="linear",
            symbol=symbol,
            side="Sell",
            orderType=order_type,
            qty=str(qty),
            reduceOnly=reduce_only
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

        if not config.bybit_client:
            logger.error("[ERROR] Bybit 클라이언트 없음")
            return {"success": False, "error": "Bybit 클라이언트 없음"}

        response = config.bybit_client.cancel_order(
            category="linear",
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
