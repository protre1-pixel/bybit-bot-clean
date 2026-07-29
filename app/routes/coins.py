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
    coins = state.get("coins", [])
    return jsonify({"coins": coins})


@coins_bp.route('/list', methods=['GET'])
@token_required
def get_coins_list():
    """코인 목록 조회"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    return jsonify({"coins": state["coins"]})


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

        if symbol in state["coins"]:
            return jsonify({"success": False, "error": "이미 추가된 코인입니다"}), 400

        # 새 코인 추가
        state["coins"].append(symbol)
        state[symbol] = create_default_coin_state(symbol)

        # 파일에 저장
        save_state(state, username)

        logger.info(f"[INFO] 새 코인 추가: {symbol.upper()}, 현재 코인: {state['coins']}")
        return jsonify({"success": True, "message": f"{symbol.upper()} 추가 완료", "coins": state["coins"]})
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

        if symbol not in state["coins"]:
            return jsonify({"success": False, "error": "존재하지 않는 코인입니다"}), 400

        # 코인 제거
        state["coins"].remove(symbol)
        if symbol in state:
            del state[symbol]

        # 파일에 저장
        save_state(state, username)

        logger.info(f"[INFO] 코인 제거: {symbol.upper()}, 현재 코인: {state['coins']}")
        return jsonify({"success": True, "message": f"{symbol.upper()} 삭제 완료", "coins": state["coins"]})
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

    if coin not in state.get("coins", []):
        return jsonify({"error": "존재하지 않는 코인"}), 400

    coin_settings = state.get("coin_settings", {})
    settings = coin_settings.get(coin, {})

    return jsonify({
        "initial_seed": settings.get("initial_seed", 1000),
        "current_seed": settings.get("current_seed", settings.get("initial_seed", 1000)),
        "leverage": settings.get("leverage", 10),
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

    if coin not in state.get("coins", []):
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
            "leverage": data.get("leverage", 10),
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


@coins_bp.route('/<coin>', methods=['POST'])
@token_required
def sell_position(coin):
    """포지션 매도"""
    from app.utils import load_trades, save_trades
    from datetime import datetime

    username = get_current_user() or 'guest'
    state = load_state(username)
    coin = coin.lower()

    if coin not in state.get("coins", []):
        return jsonify({"error": "Invalid coin"}), 400

    if coin not in state or not state[coin]["position"]:
        return jsonify({"error": "No open position"}), 400

    # 현재 가격으로 매도
    exit_price = state[coin]["current_price"]
    profit = state[coin]["profit"]

    # 거래 기록 저장
    trades = load_trades(username)

    # 수익률 계산
    actual_used_capital = state[coin]["margin"] * (state[coin]["position_ratio"] / 100)
    profit_pct = ((profit / actual_used_capital) * 100) if actual_used_capital > 0 else 0

    trade = {
        "coin": coin.upper(),
        "type": state[coin]["position"].upper(),
        "entry_price": round(state[coin]["entry_price"], 6),
        "exit_price": round(exit_price, 6),
        "entry_time": state[coin]["entry_time"],
        "exit_time": datetime.now().isoformat(),
        "profit": round(profit, 2),
        "profit_pct": round(profit_pct, 2),
        "position_size": round(state[coin]["position_size"], 8)
    }
    trades.append(trade)
    save_trades(trades, username)

    # 마진 업데이트
    state[coin]["margin"] += profit

    # 총시드 업데이트
    state["total_seed"] += profit

    # 포지션 리셋
    state[coin]["position"] = None
    state[coin]["entry_price"] = None
    state[coin]["entry_time"] = None
    state[coin]["profit"] = 0
    state[coin]["profit_pct"] = 0
    state[coin]["position_size"] = 0
    state[coin]["last_close_time"] = datetime.now().isoformat()

    # 상태 저장
    save_state(state, username)

    return jsonify({
        "success": True,
        "message": f"{coin.upper()} position closed",
        "profit": round(profit, 2),
        "new_margin": round(state[coin]["margin"], 2),
        "trade": trade
    })
