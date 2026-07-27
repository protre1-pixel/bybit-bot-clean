"""거래 로직"""
import logging
from datetime import datetime
from app.utils import load_state, save_state, load_trades, save_trades

logger = logging.getLogger(__name__)


def check_entry_signal(symbol, coin_key, state):
    """진입 신호 확인 (전봉 기준)"""
    from app.services.price_service import calculate_atr, calculate_sma

    try:
        current_price = state[coin_key]["current_price"]
        timeframe = state[coin_key].get("timeframe", 60)

        # 전봉(완성된 캔들) 기준으로 계산
        atr = calculate_atr(symbol, timeframe=timeframe)
        sma = calculate_sma(symbol, timeframe=timeframe)

        if atr is None or sma is None:
            return None

        # 이전 완성 캔들의 ATR/SMA 기반으로 신호 생성
        upper_breakout = sma + (atr * 1.5)
        lower_breakout = sma - (atr * 1.5)

        # 현재 가격이 이전 캔들의 저항선/지지선을 돌파했는지 확인
        if current_price < lower_breakout:
            return "short"
        elif current_price > upper_breakout:
            return "long"

        return None
    except Exception as e:
        print(f"[ERROR] check_entry_signal ({coin_key}): {e}")
        return None


def find_available_wallet(state):
    """사용 가능한 지갑 찾기"""
    wallets = state.get("wallets", {})
    for wallet_key in sorted(wallets.keys()):
        if not wallets[wallet_key].get("is_active"):
            return wallet_key
    return None


def auto_trade(coin_key, symbol, state, username=None):
    """자동 거래 로직 (지갑 기반) - 전봉 기준"""
    try:
        current_price = state[coin_key]["current_price"]

        if current_price == 0:
            return

        # 거래 종료 후 30분 이내는 자동 거래 비활성화 (재진입 방지)
        try:
            if "last_close_time" in state[coin_key] and state[coin_key]["last_close_time"]:
                last_close_time = datetime.fromisoformat(state[coin_key]["last_close_time"])
                elapsed = (datetime.now() - last_close_time).total_seconds()
                if elapsed < 1800:  # 1800초 = 30분
                    logger.debug(f"[DEBUG] {coin_key.upper()}: 거래 종료 후 {elapsed:.0f}초 대기 중 (30분 제한)...")
                    return
        except (ValueError, TypeError) as e:
            logger.warning(f"[WARN] last_close_time 파싱 실패 ({coin_key}): {e}")

        # 거래 진입 후 최소 1분은 TP/SL 체크 안함
        if state[coin_key]["position"] and state[coin_key]["entry_time"]:
            try:
                entry_time = datetime.fromisoformat(state[coin_key]["entry_time"])
                elapsed = (datetime.now() - entry_time).total_seconds()
                if elapsed < 60:
                    return
            except (ValueError, TypeError) as e:
                logger.warning(f"[WARN] entry_time 파싱 실패 ({coin_key}): {e}")

        # TP/SL 체크
        if state[coin_key]["position"]:
            wallets = state.get("wallets", {})
            wallet_key = state[coin_key].get("wallet_id")
            if wallet_key and wallet_key in wallets:
                tp_percent = wallets[wallet_key].get("tp", 2.0) / 100
                sl_percent = wallets[wallet_key].get("sl", 1.5) / 100
            else:
                tp_percent = 0.02
                sl_percent = 0.015

            if state[coin_key]["position"] == "long":
                if current_price > state[coin_key]["max_profit_price"]:
                    state[coin_key]["max_profit_price"] = current_price
                    state[coin_key]["sl_price"] = current_price * (1 - sl_percent)
                    logger.debug(f"[TRAILING] {coin_key.upper()}: SL 업데이트 → ${state[coin_key]['sl_price']:.6f}")

                if current_price >= state[coin_key]["tp_price"]:
                    close_trade(coin_key, current_price, "Take Profit", state, username)
                elif current_price <= state[coin_key]["sl_price"]:
                    close_trade(coin_key, state[coin_key]["sl_price"], "Stop Loss", state, username)

            elif state[coin_key]["position"] == "short":
                if current_price < state[coin_key]["max_profit_price"]:
                    state[coin_key]["max_profit_price"] = current_price
                    state[coin_key]["sl_price"] = current_price * (1 + sl_percent)
                    logger.debug(f"[TRAILING] {coin_key.upper()}: SL 업데이트 → ${state[coin_key]['sl_price']:.6f}")

                if current_price <= state[coin_key]["tp_price"]:
                    close_trade(coin_key, current_price, "Take Profit", state, username)
                elif current_price >= state[coin_key]["sl_price"]:
                    close_trade(coin_key, state[coin_key]["sl_price"], "Stop Loss", state, username)

        # 진입 신호 체크
        if not state[coin_key]["position"]:
            is_recently_closed = False
            try:
                if "last_close_time" in state[coin_key] and state[coin_key]["last_close_time"]:
                    last_close_time = datetime.fromisoformat(state[coin_key]["last_close_time"])
                    elapsed = (datetime.now() - last_close_time).total_seconds()
                    if elapsed < 1800:  # 1800초 = 30분
                        is_recently_closed = True
            except (ValueError, TypeError):
                pass

            if not is_recently_closed:
                signal = check_entry_signal(symbol, coin_key, state)
                if signal:
                    # 사용 가능한 지갑 찾기
                    available_wallet = find_available_wallet(state)

                    if available_wallet:
                        wallets = state.get("wallets", {})
                        wallet = wallets[available_wallet]
                        current_seed = wallet.get("current_seed", 1000)
                        entry_percent = wallet.get("entry_percent", 75) / 100
                        leverage = wallet.get("leverage", 10)
                        tp_percent = wallet.get("tp", 2.0) / 100
                        sl_percent = wallet.get("sl", 1.5) / 100

                        # 포지션 계산
                        position_nominal = current_seed * entry_percent * leverage
                        position_size = position_nominal / current_price

                        # 실제 주문 (라이브/페이퍼)
                        from app.services.order_service import place_buy_order, place_sell_order
                        mode = state.get("mode", "paper")

                        if signal == "long":
                            order_result = place_buy_order(f"{coin_key.upper()}USDT", position_size, mode=mode)
                        else:  # short
                            order_result = place_sell_order(f"{coin_key.upper()}USDT", position_size, mode=mode)

                        if not order_result.get("success"):
                            logger.error(f"[ERROR] {coin_key.upper()} 주문 실패: {order_result.get('error')}")
                            return

                        # 거래 진입 상태 저장
                        state[coin_key]["position"] = signal
                        state[coin_key]["entry_price"] = current_price
                        state[coin_key]["entry_time"] = datetime.now().isoformat()
                        state[coin_key]["max_profit_price"] = current_price
                        state[coin_key]["wallet_id"] = available_wallet
                        state[coin_key]["position_size"] = position_size
                        state[coin_key]["order_id"] = order_result.get("order_id")

                        # SL/TP 설정
                        if signal == "long":
                            state[coin_key]["tp_price"] = current_price * (1 + tp_percent)
                            state[coin_key]["sl_price"] = current_price * (1 - sl_percent)
                        else:
                            state[coin_key]["tp_price"] = current_price * (1 - tp_percent)
                            state[coin_key]["sl_price"] = current_price * (1 + sl_percent)

                        # 지갑 활성화
                        wallet["is_active"] = True
                        wallet["assigned_coin"] = coin_key

                        logger.info(f"[{coin_key.upper()}] {signal.upper()} 진입 ({available_wallet}, {mode}): {current_price} | TP: ${state[coin_key]['tp_price']:.6f} | SL: ${state[coin_key]['sl_price']:.6f}")
                    else:
                        logger.debug(f"[{coin_key.upper()}] 신호 발생하나 사용 가능한 지갑 없음 (모두 거래 중)")
    except Exception as e:
        logger.error(f"[ERROR] auto_trade ({coin_key}): {e}")


def close_trade(coin_key, exit_price, reason, state, username=None):
    """거래 종료 및 기록"""
    try:
        if state[coin_key]["position"] == "long":
            profit = (exit_price - state[coin_key]["entry_price"]) * state[coin_key]["position_size"]
        else:  # short
            profit = (state[coin_key]["entry_price"] - exit_price) * state[coin_key]["position_size"]

        # 수익률: 진입가 기준 포지션 변화율
        if state[coin_key]["position"] == "long":
            profit_pct = ((exit_price - state[coin_key]["entry_price"]) / state[coin_key]["entry_price"]) * 100
        else:  # short
            profit_pct = ((state[coin_key]["entry_price"] - exit_price) / state[coin_key]["entry_price"]) * 100

        # 실제 매도 주문 (라이브/페이퍼)
        from app.services.order_service import place_sell_order
        mode = state.get("mode", "paper")
        position_size = state[coin_key].get("position_size", 0)

        if mode == "live" and position_size > 0:
            # 라이브 모드: 실제 매도
            order_result = place_sell_order(f"{coin_key.upper()}USDT", position_size, mode=mode)
            if not order_result.get("success"):
                logger.error(f"[ERROR] {coin_key.upper()} 매도 주문 실패: {order_result.get('error')}")
        else:
            # 페이퍼 모드: 시뮬레이션
            logger.info(f"[PAPER] 매도: {coin_key.upper()} × {position_size}")

        # 거래 기록 저장
        trades = load_trades(username)

        # 실제 손실/수익 기반으로 재계산하여 일관성 확보
        actual_position_size = state[coin_key]["position_size"]
        actual_entry_price = state[coin_key]["entry_price"]
        actual_profit = profit
        actual_profit_pct = profit_pct

        trade = {
            "coin": coin_key.upper(),
            "type": state[coin_key]["position"].upper(),
            "entry_price": round(actual_entry_price, 6),
            "exit_price": round(exit_price, 6),
            "entry_time": state[coin_key]["entry_time"],
            "exit_time": datetime.now().isoformat(),
            "profit": round(profit, 2),
            "profit_pct": round(profit_pct, 2),
            "position_size": round(actual_position_size, 8),
            "reason": reason
        }
        trades.append(trade)
        save_trades(trades, username)

        # 지갑 손익 누적 (지갑 기반 복리)
        wallet_id = state[coin_key].get("wallet_id")
        if wallet_id and "wallets" in state and wallet_id in state["wallets"]:
            wallet = state["wallets"][wallet_id]
            wallet["current_seed"] = wallet.get("current_seed", 1000) + profit
            wallet["is_active"] = False
            wallet["assigned_coin"] = None
            logger.info(f"[{wallet_id}] 손익 누적: ${profit:.2f} → 새로운 시드: ${wallet['current_seed']:.2f}")

        # 마진 업데이트 (하위 호환성 유지)
        state[coin_key]["margin"] += profit

        # 총시드 업데이트 (모든 지갑 손익 합산)
        state["total_seed"] += profit

        # 포지션 리셋
        state[coin_key]["position"] = None
        state[coin_key]["entry_price"] = None
        state[coin_key]["entry_time"] = None
        state[coin_key]["profit"] = 0
        state[coin_key]["profit_pct"] = 0
        state[coin_key]["position_size"] = 0
        state[coin_key]["max_profit_price"] = None
        state[coin_key]["tp_price"] = None
        state[coin_key]["sl_price"] = None
        state[coin_key]["wallet_id"] = None
        state[coin_key]["last_close_time"] = datetime.now().isoformat()

        logger.info(f"[{coin_key.upper()}] 거래 종료: {reason}, 수익: ${profit:.2f}")
    except Exception as e:
        logger.error(f"[ERROR] close_trade ({coin_key}): {e}")
