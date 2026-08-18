"""설정 라우트"""
import logging
from flask import Blueprint, jsonify, request
from app.utils import token_required, get_current_user, load_state, save_state
from app.services import get_top_coins_by_volume_volatility, load_cached_coins

logger = logging.getLogger(__name__)

settings_bp = Blueprint('settings', __name__, url_prefix='/api')


@settings_bp.route('/settings', methods=['GET'])
@token_required
def get_all_settings():
    """모든 코인 설정 조회"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    result = {}
    for coin in state.get("available_coins", []):
        if coin in state:
            result[coin] = {
                "leverage": state[coin].get("leverage", 5),
                "margin": state[coin].get("margin", 1000),
                "position_ratio": state[coin].get("position_ratio", 75),
                "tp": state[coin].get("tp", 2.0),
                "sl": state[coin].get("sl", 1.5),
                "timeframe": state[coin].get("timeframe", 60)
            }
    return jsonify(result)


@settings_bp.route('/settings/<coin>', methods=['GET'])
@token_required
def get_settings(coin):
    """코인 설정 조회"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    coin = coin.lower()
    if coin not in state.get("available_coins", []):
        return jsonify({"error": "Invalid coin"}), 400

    if coin not in state:
        return jsonify({"error": "Coin not found"}), 404

    return jsonify({
        "leverage": state[coin].get("leverage", 5),
        "margin": state[coin].get("margin", 1000),
        "position_ratio": state[coin].get("position_ratio", 75),
        "tp": state[coin].get("tp", 2.0),
        "sl": state[coin].get("sl", 1.5),
        "timeframe": state[coin].get("timeframe", 60)
    })


@settings_bp.route('/settings/<coin>', methods=['POST'])
@token_required
def set_settings(coin):
    """코인 설정 저장"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    coin = coin.lower()
    if coin not in state.get("available_coins", []):
        return jsonify({"error": "Invalid coin"}), 400

    if coin not in state:
        return jsonify({"error": "Coin not found"}), 404

    data = request.get_json()

    if "timeframe" in data:
        state[coin]["timeframe"] = int(data["timeframe"])
    if "margin" in data:
        state[coin]["margin"] = float(data["margin"])
    if "leverage" in data:
        state[coin]["leverage"] = int(data["leverage"])
    if "position_ratio" in data:
        state[coin]["position_ratio"] = float(data["position_ratio"])
    if "tp" in data:
        state[coin]["tp"] = float(data["tp"])
    if "sl" in data:
        state[coin]["sl"] = float(data["sl"])

    # 파일에 저장
    save_state(state, username)

    return jsonify({
        "success": True,
        "settings": {
            "leverage": state[coin].get("leverage", 5),
            "margin": state[coin].get("margin", 1000),
            "position_ratio": state[coin].get("position_ratio", 75),
            "tp": state[coin].get("tp", 2.0),
            "sl": state[coin].get("sl", 1.5),
            "timeframe": state[coin].get("timeframe", 60)
        }
    })


@settings_bp.route('/global-settings', methods=['GET'])
@token_required
def get_global_settings():
    """전역 설정 조회"""
    username = get_current_user() or 'guest'
    state = load_state(username)

    total_seed = state.get("total_seed", 3000)
    max_trades = state.get("max_trades", 3)
    per_trade_amount = total_seed / max_trades if max_trades > 0 else 0
    mode = state.get("mode", "paper")

    # 라이브 모드면 실제 지갑 잔액 조회
    actual_balance = None
    if mode == "live":
        try:
            from app.services.wallet_service import get_bybit_balance
            actual_balance = get_bybit_balance()
        except Exception as e:
            logger.warning(f"[WARN] 지갑 잔액 조회 실패: {e}")

    # 캐시된 코인 확인 (24시간 유지)
    cached = load_cached_coins()

    if not cached:
        available_coins = get_top_coins_by_volume_volatility()
    else:
        available_coins = cached

    # USDC 제외
    excluded = ['USDC', 'USDT', 'BUSD', 'DAI', 'TUSD', 'FDUSD']
    if available_coins:
        available_coins = [c for c in available_coins if c.upper() not in excluded]

    result = {
        "total_seed": total_seed,
        "max_trades": max_trades,
        "per_trade_amount": round(per_trade_amount, 2),
        "coins": state.get("available_coins", []),
        "available_coins": available_coins,
        "mode": mode
    }

    # 라이브 모드면 실제 지갑 잔액 추가
    if mode == "live" and actual_balance is not None:
        result["actual_balance"] = round(actual_balance, 2)
        result["balance_info"] = {
            "ui_capital": total_seed,
            "actual_balance": round(actual_balance, 2),
            "is_valid": total_seed <= actual_balance
        }

    return jsonify(result)


@settings_bp.route('/global-settings', methods=['POST'])
@token_required
def set_global_settings():
    """전역 설정 저장"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    data = request.get_json()

    if not data:
        return jsonify({"error": "유효한 JSON 데이터가 필요합니다"}), 400

    # 지갑 재분배 필요 여부 확인
    old_total_seed = state.get("total_seed")
    old_max_trades = state.get("max_trades")
    needs_wallet_rebalance = False

    if "total_seed" in data:
        state["total_seed"] = float(data["total_seed"])
        if state["total_seed"] != old_total_seed:
            needs_wallet_rebalance = True

    if "max_trades" in data:
        max_trades = int(data["max_trades"])
        if max_trades < 1 or max_trades > 20:
            return jsonify({"error": "거래허용 건수는 1~20 사이여야 합니다"}), 400
        state["max_trades"] = max_trades
        if max_trades != old_max_trades:
            needs_wallet_rebalance = True

    # 코인 선택
    if "coins" in data:
        selected_coins = data.get("coins", [])
        if len(selected_coins) > state.get("max_trades", 5):
            return jsonify({
                "error": f"선택한 코인({len(selected_coins)})이 거래허용 건수({state.get('max_trades', 5)})를 초과합니다"
            }), 400
        state["available_coins"] = selected_coins  # ← coins 대신 available_coins

    # 지갑 재분배 (total_seed 또는 max_trades 변경 시)
    if needs_wallet_rebalance:
        total_seed = state.get("total_seed", 3000)
        max_trades = state.get("max_trades", 3)
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
        logger.info(f"[INFO] {username} 지갑 재분배: ${total_seed} ÷ {max_trades}개 = 각 ${wallet_seed:.2f}")

    # 상태 저장
    save_state(state, username)

    total_seed = state.get("total_seed", 3000)
    max_trades = state.get("max_trades", 5)
    per_trade_amount = total_seed / max_trades if max_trades > 0 else 0

    return jsonify({
        "success": True,
        "total_seed": total_seed,
        "max_trades": max_trades,
        "per_trade_amount": round(per_trade_amount, 2)
    })


@settings_bp.route('/user/settings/api', methods=['POST'])
@token_required
def save_user_api_settings():
    """사용자 API 키 저장"""
    try:
        username = get_current_user()
        if not username:
            return jsonify({"success": False, "error": "인증 필요"}), 401

        data = request.get_json()
        api_key = data.get('api_key', '').strip()
        api_secret = data.get('api_secret', '').strip()

        if not api_key or not api_secret:
            return jsonify({"success": False, "error": "API 키와 시크릿을 입력하세요"}), 400

        # 사용자 상태 로드
        user_state = load_state(username)
        user_state['api_key'] = api_key
        user_state['api_secret'] = api_secret
        user_state['mode'] = 'live'

        # 저장
        save_state(user_state, username)

        # Bybit 클라이언트 재초기화 (Paper 모드에서도 Bybit 사용 가능하게)
        # BYBIT_DEMO 설정을 그대로 존중해야 함 - 안 그러면 데모 환경에서 저장해도
        # 실전 서버(api.bybit.com)로 튕겨버림
        from pybit.unified_trading import HTTP
        try:
            from app import config
            config.bybit_client = HTTP(
                testnet=False,
                demo=config.BYBIT_DEMO,
                api_key=api_key,
                api_secret=api_secret
            )
            logger.info(f"[INFO] {username} - Bybit API 클라이언트 재초기화 성공 (demo={config.BYBIT_DEMO})")
        except Exception as e:
            logger.warning(f"[WARN] Bybit 클라이언트 재초기화 실패: {e}")

        logger.info(f"[INFO] {username} - API 키 저장, 라이브 모드 전환")
        return jsonify({"success": True, "message": "API 키가 저장되었습니다. Paper/Live 모드 모두 Bybit 가격 사용", "mode": "live"})
    except Exception as e:
        logger.error(f"[ERROR] save_user_api_settings: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
