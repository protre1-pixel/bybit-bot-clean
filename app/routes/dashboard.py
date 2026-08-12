"""대시보드 라우트 (상태, 통계, 거래기록)"""
import logging
from datetime import datetime
from flask import Blueprint, jsonify, request
from app.utils import token_required, get_current_user, load_state, save_state, state_transaction, load_trades
from app.services.trading_service import close_trade

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

    # available_coins + 거래 중인 모든 코인 (거래 종료까지 유지)
    coins_to_show = set(state.get("available_coins", []))
    for key in state.keys():
        if isinstance(state[key], dict) and state[key].get("position"):
            coins_to_show.add(key)

    for coin in coins_to_show:
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
    result["coins"] = list(coins_to_show)  # ← available_coins + 거래 중인 코인 모두!
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
    state = load_state(username)

    target_year_month = f"{year:04d}-{month:02d}"
    current_total_seed = state.get('total_seed', 3000)

    # 해당 월 이전까지의 수익 계산 (이전 달의 마지막 시드 구하기)
    profit_before_month = 0
    for trade in trades:
        try:
            exit_date = datetime.fromisoformat(trade['exit_time']).strftime('%Y-%m-%d')
            exit_year_month = exit_date[:7]

            # 대상 월보다 이전 거래만 포함
            if exit_year_month < target_year_month:
                profit_before_month += trade.get('profit', 0)
        except (ValueError, TypeError, KeyError):
            pass

    # 초기 시드 = 현재 총시드 - 이전 월까지의 수익 - 현재 월 수익
    initial_capital = state.get('total_seed', 3000)
    profit_this_month = 0

    daily_profit = {}

    # 현재 월의 거래 처리 (매도 시간 기준)
    for trade in trades:
        try:
            # exit_time(매도 시간) 기준으로 날짜 추출
            exit_date = datetime.fromisoformat(trade['exit_time']).strftime('%Y-%m-%d')
            exit_year_month = exit_date[:7]

            if exit_year_month == target_year_month:
                if exit_date not in daily_profit:
                    daily_profit[exit_date] = {
                        'total_trades': 0,
                        'win_trades': 0,
                        'loss_trades': 0,
                        'total_profit': 0,
                        'current_seed': 0
                    }

                profit = trade.get('profit', 0)
                profit_this_month += profit
                daily_profit[exit_date]['total_trades'] += 1
                daily_profit[exit_date]['total_profit'] += profit

                if profit > 0:
                    daily_profit[exit_date]['win_trades'] += 1
                else:
                    daily_profit[exit_date]['loss_trades'] += 1
        except (ValueError, TypeError, KeyError) as e:
            logger.warning(f"[WARN] 거래 날짜 파싱 실패: {e}")

    # 이 달의 초기 시드 = 현재 총시드 - 이 달 수익 (= 전달 마지막 시드)
    initial_seed = current_total_seed - profit_this_month

    # 날짜 정렬 후 누적 시드 계산
    sorted_dates = sorted(daily_profit.keys())
    cumulative = 0
    for date in sorted_dates:
        cumulative += daily_profit[date]['total_profit']
        daily_profit[date]['current_seed'] = round(initial_seed + cumulative, 2)

    return jsonify({
        "year": year,
        "month": month,
        "daily_profit": daily_profit,
        "total_seed": round(current_total_seed, 2),
        "initial_seed": round(initial_seed, 2),
        "profit_before_month": round(profit_before_month, 2),
        "profit_this_month": round(profit_this_month, 2)
    })


@dashboard_bp.route('/trades/<date>', methods=['GET'])
@token_required
def get_trades_by_date(date):
    """특정 날짜의 거래 내역 조회 (매도 시간 기준)"""
    username = get_current_user() or 'guest'
    trades = load_trades(username)

    date_trades = []
    for trade in trades:
        try:
            # exit_time(매도 시간) 기준으로 필터링
            exit_date = datetime.fromisoformat(trade['exit_time']).strftime('%Y-%m-%d')
            if exit_date == date:
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


@dashboard_bp.route('/sell/<coin>', methods=['POST'])
@token_required
def sell_coin(coin):
    """강제 매도 (즉시 포지션 종료)"""
    try:
        username = get_current_user() or 'guest'
        coin_key = coin.lower()

        # 불러오기→종료 처리→저장을 하나의 락으로 묶어서, 백그라운드 가격 업데이트
        # 루프가 그 사이에 끼어들어 방금 닫은 포지션을 다시 덮어쓰는 것을 방지
        with state_transaction(username) as state:
            if coin_key not in state:
                return jsonify({"success": False, "error": "코인 정보 없음"}), 400

            coin_data = state[coin_key]

            if not coin_data.get("position"):
                return jsonify({"success": False, "error": "진행 중인 포지션 없음"}), 400

            current_price = coin_data.get("current_price", 0)
            if current_price == 0:
                return jsonify({"success": False, "error": "현재 가격 조회 실패"}), 400

            profit = close_trade(coin_key, current_price, "Manual Close", state, username)

        logger.info(f"[{coin_key.upper()}] 강제 매도 완료: 수익 ${profit:.2f}")
        return jsonify({
            "success": True,
            "message": f"{coin.upper()} 매도 완료",
            "profit": round(profit, 2)
        })

    except Exception as e:
        logger.error(f"[ERROR] 강제 매도 실패 ({coin}): {e}")
        return jsonify({"success": False, "error": str(e)}), 500
