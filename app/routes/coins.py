"""코인 관리 라우트"""
import logging
from flask import Blueprint, jsonify, request
from app.utils import token_required, get_current_user, load_state, save_state, create_default_coin_state
from app.services import get_current_price

logger = logging.getLogger(__name__)

coins_bp = Blueprint('coins', __name__, url_prefix='/api/coins')


@coins_bp.route('', methods=['GET'])
@token_required
def get_coins():
    """활성 코인 목록 조회"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    coins = state.get("available_coins", [])
    return jsonify({"coins": coins})


@coins_bp.route('/list', methods=['GET'])
@token_required
def get_coins_list():
    """코인 목록 조회"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    return jsonify({"coins": state["available_coins"]})


@coins_bp.route('/add', methods=['POST'])
@token_required
def add_coin():
    """새 코인 추가"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    try:
        data = request.json
        if not data:
            return jsonify({"success": False, "error": "유효한 JSON 데이터가 필요합니다"}), 400

        symbol = data.get('symbol', '').lower().strip()

        if not symbol:
            return jsonify({"success": False, "error": "심볼을 입력해주세요"}), 400

        if not symbol.isalpha():
            return jsonify({"success": False, "error": "심볼은 영문만 가능합니다"}), 400

        if symbol in state["available_coins"]:
            return jsonify({"success": False, "error": "이미 추가된 코인입니다"}), 400

        # 새 코인 추가
        state["available_coins"].append(symbol)
        state[symbol] = create_default_coin_state(symbol)

        # 파일에 저장
        save_state(state, username)

        logger.info(f"[INFO] 새 코인 추가: {symbol.upper()}, 현재 코인: {state['available_coins']}")
        return jsonify({"success": True, "message": f"{symbol.upper()} 추가 완료", "coins": state["available_coins"]})
    except Exception as e:
        logger.error(f"[ERROR] add_coin: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@coins_bp.route('/remove', methods=['POST'])
@token_required
def remove_coin():
    """코인 제거"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    try:
        data = request.json
        if not data:
            return jsonify({"success": False, "error": "유효한 JSON 데이터가 필요합니다"}), 400

        symbol = data.get('symbol', '').lower().strip()

        if not symbol:
            return jsonify({"success": False, "error": "심볼을 입력해주세요"}), 400

        if symbol not in state["available_coins"]:
            return jsonify({"success": False, "error": "존재하지 않는 코인입니다"}), 400

        # 코인 제거
        state["available_coins"].remove(symbol)
        if symbol in state:
            del state[symbol]

        # 파일에 저장
        save_state(state, username)

        logger.info(f"[INFO] 코인 제거: {symbol.upper()}, 현재 코인: {state['available_coins']}")
        return jsonify({"success": True, "message": f"{symbol.upper()} 삭제 완료", "coins": state["available_coins"]})
    except Exception as e:
        logger.error(f"[ERROR] remove_coin: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@coins_bp.route('/<coin>/settings', methods=['GET'])
@token_required
def get_coin_settings(coin):
    """코인별 설정 조회"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    coin = coin.lower()

    if coin not in state.get("available_coins", []):
        return jsonify({"error": "존재하지 않는 코인"}), 400

    coin_settings = state.get("coin_settings", {})
    settings = coin_settings.get(coin, {})

    return jsonify({
        "initial_seed": settings.get("initial_seed", 1000),
        "current_seed": settings.get("current_seed", settings.get("initial_seed", 1000)),
        "leverage": settings.get("leverage", 5),
        "tp": settings.get("tp", 2.0),
        "sl": settings.get("sl", 1.5),
        "entry_percent": settings.get("entry_percent", 75)
    })


@coins_bp.route('/<coin>/settings', methods=['POST'])
@token_required
def set_coin_settings(coin):
    """코인별 설정 저장"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    coin = coin.lower()

    if coin not in state.get("available_coins", []):
        return jsonify({"success": False, "error": "존재하지 않는 코인"}), 400

    try:
        data = request.get_json()

        # coin_settings 구조 초기화
        if "coin_settings" not in state:
            state["coin_settings"] = {}

        # 현재 시드 유지
        current_settings = state["coin_settings"].get(coin, {})
        current_seed = current_settings.get("current_seed", data.get("initial_seed", 1000))

        state["coin_settings"][coin] = {
            "initial_seed": data.get("initial_seed", 1000),
            "current_seed": current_seed,
            "leverage": data.get("leverage", 5),
            "tp": data.get("tp", 2.0),
            "sl": data.get("sl", 1.5),
            "entry_percent": data.get("entry_percent", 75)
        }

        # 상태 저장
        save_state(state, username)

        logger.info(f"[INFO] {coin.upper()} 설정 저장: {state['coin_settings'][coin]}")
        return jsonify({"success": True, "message": f"{coin.upper()} 설정이 저장되었습니다"})
    except Exception as e:
        logger.error(f"[ERROR] set_coin_settings ({coin}): {e}")
        return jsonify({"success": False, "error": str(e)}), 500
