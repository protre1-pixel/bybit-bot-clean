"""대시보드 라우트 (상태, 통계, 거래기록)"""
import logging
from datetime import datetime
from flask import Blueprint, jsonify, request
from app.utils import token_required, get_current_user, load_state, save_state, load_trades

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/api')


@dashboard_bp.route('/status', methods=['GET'])
@token_required
def get_status():
    """현재 상태 조회 (모든 코인)"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    result = {}
    total_profit = 0
    total_margin = 0

    for coin in state.get("coins", []):
        if coin in state:
            coin_data = state[coin]
            result[coin] = {
                "current_price": coin_data["current_price"],
                "position": coin_data["position"],
                "entry_price": coin_data["entry_price"] if coin_data["entry_price"] else 0,
                "sl_price": coin_data.get("sl_price"),
                "tp_price": coin_data.get("tp_price"),
                "margin": round(coin_data["margin"], 2),
                "profit": round(coin_data["profit"], 2),
                "profit_pct": round(coin_data["profit_pct"], 2),
                "entry_time": coin_data["entry_time"]
            }
            total_profit += coin_data["profit"]
            total_margin += coin_data["margin"]

    initial_capital = state.get("total_seed", 3000)
    current_capital = initial_capital + total_profit
    roi_pct = (total_profit / initial_capital * 100) if initial_capital > 0 else 0

    result["total"] = {
        "profit": round(total_profit, 2),
        "current_capital": round(current_capital, 2),
        "initial_capital": initial_capital,
        "roi_pct": round(roi_pct, 2)
    }
    result["coins"] = state.get("coins", [])
    result["total_seed"] = state.get("total_seed", 3000)
    result["mode"] = state.get("mode", "paper")
    result["has_api_key"] = bool(state.get("api_key"))
    result["max_trades"] = state.get("max_trades", 3)

    # 지갑 정보 추가 (지갑 기반 복리 시스템)
    wallets = state.get("wallets", {})
    result["wallets"] = {}
    for wallet_key, wallet in wallets.items():
        result["wallets"][wallet_key] = {
            "current_seed": round(wallet.get("current_seed", 0), 2),
            "initial_seed": round(wallet.get("initial_seed", 0), 2),
            "is_active": wallet.get("is_active", False),
            "assigned_coin": wallet.get("assigned_coin")
        }

    return jsonify(result)


@dashboard_bp.route('/trades', methods=['GET'])
@token_required
def get_trades():
    """거래 기록 조회"""
    username = get_current_user() or 'guest'
    trades = load_trades(username)
    return jsonify(trades)


@dashboard_bp.route('/stats', methods=['GET'])
@token_required
def get_stats():
    """통계"""
    username = get_current_user() or 'guest'
    trades = load_trades(username)

    if not trades:
        return jsonify({
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "win_rate": 0,
            "total_profit": 0,
            "avg_profit": 0
        })

    win_trades = len([t for t in trades if t.get("profit", 0) > 0])
    loss_trades = len([t for t in trades if t.get("profit", 0) < 0])
    total_profit = sum([t.get("profit", 0) for t in trades])

    return jsonify({
        "total_trades": len(trades),
        "win_trades": win_trades,
        "loss_trades": loss_trades,
        "win_rate": round((win_trades / len(trades) * 100), 1) if trades else 0,
        "total_profit": round(total_profit, 2),
        "avg_profit": round(total_profit / len(trades), 2) if trades else 0
    })


@dashboard_bp.route('/mode', methods=['GET'])
@token_required
def get_mode():
    """현재 모드"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    return jsonify({"mode": state["mode"]})


@dashboard_bp.route('/mode/<mode>', methods=['POST'])
@token_required
def set_mode(mode):
    """모드 변경"""
    username = get_current_user() or 'guest'
    state = load_state(username)
    if mode in ["paper", "live"]:
        state["mode"] = mode
        save_state(state, username)
        return jsonify({"success": True, "mode": state["mode"]})
    return jsonify({"error": "Invalid mode"}), 400


@dashboard_bp.route('/calendar/<int:year>/<int:month>', methods=['GET'])
@token_required
def get_calendar_data(year, month):
    """달력 데이터 조회 (날짜별 수익금)"""
    username = get_current_user() or 'guest'
    trades = load_trades(username)

    daily_profit = {}
    for trade in trades:
        try:
            entry_date = datetime.fromisoformat(trade['entry_time']).strftime('%Y-%m-%d')
            entry_year_month = entry_date[:7]
            current_year_month = f"{year:04d}-{month:02d}"

            if entry_year_month == current_year_month:
                if entry_date not in daily_profit:
                    daily_profit[entry_date] = {'profit': 0, 'count': 0}
                daily_profit[entry_date]['profit'] += trade.get('profit', 0)
                daily_profit[entry_date]['count'] += 1
        except (ValueError, TypeError, KeyError) as e:
            logger.warning(f"[WARN] 거래 날짜 파싱 실패: {e}")

    return jsonify({
        "year": year,
        "month": month,
        "daily_profit": daily_profit
    })


@dashboard_bp.route('/trades/<date>', methods=['GET'])
@token_required
def get_trades_by_date(date):
    """특정 날짜의 거래 내역 조회"""
    username = get_current_user() or 'guest'
    trades = load_trades(username)

    date_trades = []
    for trade in trades:
        try:
            entry_date = datetime.fromisoformat(trade['entry_time']).strftime('%Y-%m-%d')
            if entry_date == date:
                date_trades.append(trade)
        except (ValueError, TypeError, KeyError) as e:
            logger.warning(f"[WARN] 거래 날짜 필터링 실패: {e}")

    return jsonify({"date": date, "trades": date_trades})


@dashboard_bp.route('/wallet/balance', methods=['GET'])
@token_required
def get_wallet_balance():
    """Bybit 실제 자금 조회"""
    from app.services.wallet_service import get_bybit_balance

    balance = get_bybit_balance()

    if balance is None:
        return jsonify({
            "success": False,
            "error": "Bybit 잔액 조회 실패",
            "balance": None
        }), 400

    return jsonify({
        "success": True,
        "balance": round(balance, 2),
        "currency": "USDT"
    })


@dashboard_bp.route('/wallet/validate', methods=['POST'])
@token_required
def validate_capital():
    """UI 초기자본 검증"""
    from app.services.wallet_service import validate_trading_capital

    username = get_current_user() or 'guest'
    data = request.get_json()
    ui_capital = data.get('ui_capital', 0)

    result = validate_trading_capital(ui_capital, username)

    if result.get('is_valid'):
        return jsonify(result)
    else:
        return jsonify(result), 400
