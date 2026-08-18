"""거래 라우트 (시작, 중지, 상태)"""
import logging
from flask import Blueprint, jsonify
from app.utils import token_required, get_current_user, load_state, save_state

logger = logging.getLogger(__name__)

trading_bp = Blueprint('trading', __name__, url_prefix='/api/trading')


@trading_bp.route('/start', methods=['POST'])
@token_required
def start_trading():
    """거래 시작 (자금 검증 포함)"""
    from app.services.wallet_service import validate_trading_capital

    username = get_current_user() or 'guest'
    state = load_state(username)

    # 선별된 코인 확인
    from app.services import load_cached_coins, get_top_coins_by_volume
    cached = load_cached_coins()
    if not cached:
        available_coins = get_top_coins_by_volume()
    else:
        available_coins = cached

    if not available_coins:
        return jsonify({"error": "선별된 코인이 없습니다"}), 400

    # 기존 코인 데이터 모두 삭제 (새로 시작)
    for key in list(state.keys()):
        if isinstance(state[key], dict) and "last_close_time" in state[key]:
            del state[key]  # 모든 코인 데이터 제거

    # 선별된 코인을 state에 설정
    state["available_coins"] = available_coins

    total_seed = state.get("total_seed", 3000)

    # 자금 검증 (Live 모드일 때만 엄격하게)
    if state.get("mode") == "live":
        validation_result = validate_trading_capital(total_seed, username)
        if not validation_result.get("is_valid"):
            logger.warning(f"[WARN] {username} 자금 검증 실패: {validation_result.get('error')}")
            return jsonify({
                "success": False,
                "error": validation_result.get('error'),
                "bybit_balance": validation_result.get('bybit_balance'),
                "ui_capital": total_seed
            }), 400

    # 지갑 시스템 초기화 (거래허용 건수 = 지갑 개수)
    max_trades = state.get("max_trades", 3)
    wallet_seed = total_seed / max_trades if max_trades > 0 else 0

    # 기존 지갑 모두 초기화 (새로운 금액으로 재분배)
    state["wallets"] = {}

    # 지갑 생성 (새로 분배)
    for wallet_id in range(1, max_trades + 1):
        wallet_key = f"wallet_{wallet_id}"
        state["wallets"][wallet_key] = {
            "initial_seed": wallet_seed,
            "current_seed": wallet_seed,
            "assigned_coin": None,
            "is_active": False,
            "entry_percent": 75,
            "leverage": 5,
            "tp": 2.0,
            "sl": 3.0
        }

    # 기존 coin_settings 유지 (하위 호환성)
    if "coin_settings" not in state:
        state["coin_settings"] = {}

    for coin in state.get("available_coins", []):
        if coin not in state["coin_settings"]:
            state["coin_settings"][coin] = {}

    state["trading_enabled"] = True
    save_state(state, username)

    logger.info(f"[INFO] {username} 거래 시작 - 선별 코인: {state['available_coins']}, 지갑: {max_trades}개, 각 지갑: ${wallet_seed:.2f}, 모드: {state.get('mode')}")
    return jsonify({
        "success": True,
        "message": "거래가 시작되었습니다",
        "trading_enabled": True,
        "coins": state["available_coins"],
        "max_trades": max_trades,
        "wallet_seed": round(wallet_seed, 2),
        "wallets_created": max_trades
    })


@trading_bp.route('/stop', methods=['POST'])
@token_required
def stop_trading():
    """거래 중지"""
    username = get_current_user() or 'guest'
    state = load_state(username)

    state["trading_enabled"] = False
    save_state(state, username)

    logger.info(f"[INFO] {username} 거래 중지")
    return jsonify({
        "success": True,
        "message": "거래가 중지되었습니다",
        "trading_enabled": False
    })


@trading_bp.route('/status', methods=['GET'])
@token_required
def trading_status():
    """거래 상태 조회"""
    username = get_current_user() or 'guest'
    state = load_state(username)

    return jsonify({
        "trading_enabled": state.get("trading_enabled", False),
        "coins": state.get("available_coins", []),
        "mode": state.get("mode", "paper")
    })


@trading_bp.route('/reset', methods=['POST'])
@token_required
def reset_all():
    """모든 상태 초기화 - 모든 코인 삭제"""
    try:
        username = get_current_user() or 'guest'
        state = load_state(username)

        from app.utils import load_trades, save_trades
        trades = load_trades(username)
        total_profit = sum([t.get("profit", 0) for t in trades])

        # 파일 초기화
        save_trades([], username)

        # state의 모든 코인의 상태 초기화 (과거 거래 코인도 포함)
        for key in list(state.keys()):
            if isinstance(state[key], dict) and "current_price" in state[key]:
                # 이것은 코인 데이터입니다
                coin = key
                state[coin]["position"] = None
                state[coin]["entry_price"] = None
                state[coin]["entry_time"] = None
                state[coin]["margin"] = 0
                state[coin]["position_size"] = 0
                state[coin]["profit"] = 0
                state[coin]["profit_pct"] = 0
                state[coin]["max_profit_price"] = None
                state[coin]["min_profit_price"] = None
                state[coin]["sl_price"] = None
                state[coin]["tp_price"] = None
                state[coin]["last_close_time"] = None
                state[coin]["squeeze_status"] = "normal"
                state[coin]["prev_band_width"] = None
                state[coin]["squeeze_width"] = None
                state[coin]["profit_mode"] = "normal"
                state[coin]["trailing_max_price"] = None

        # 모든 코인 삭제
        state["available_coins"] = []
        state["coin_settings"] = {}  # coin_settings도 초기화

        # 거래 비활성화 (UI 버튼도 거래시작으로 변경되도록)
        state["trading_enabled"] = False

        # 모든 지갑 재분배 (현재 설정에 맞게)
        max_trades = state.get("max_trades", 3)
        total_seed = state.get("total_seed", 3000)
        wallet_seed = total_seed / max_trades if max_trades > 0 else 0

        state["wallets"] = {}
        for wallet_id in range(1, max_trades + 1):
            wallet_key = f"wallet_{wallet_id}"
            state["wallets"][wallet_key] = {
                "initial_seed": wallet_seed,
                "current_seed": wallet_seed,
                "assigned_coin": None,
                "is_active": False,
                "entry_percent": 75,
                "leverage": 5,
                "tp": 2.0,
                "sl": 3.0
            }

        # 상태 저장
        save_state(state, username)

        logger.info(f"[INFO] 시스템 초기화: 누적 수익 ${total_profit:.2f}, 모든 코인 삭제됨")

        return jsonify({
            "success": True,
            "message": "시스템 초기화 완료 - 모든 코인이 삭제되었습니다. 다시 거래하려면 코인을 추가해주세요.",
            "total_profit_accumulated": round(total_profit, 2),
            "coins": []
        })
    except Exception as e:
        logger.error(f"[ERROR] reset_all 함수 오류: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
