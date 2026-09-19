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
    """달력 데이터 조회 (날짜별 수익금)

    [2026-09-19 수정] 기존 로직은 조회하는 "월"마다 매번
    "오늘 시점의 실시간 total_seed - 그 달 수익"으로 그 달의 초기 시드를 역산했다.
    이러면 오늘 시점의 total_seed에는 그 달 이후(미래) 달의 수익까지 이미 반영돼 있는데,
    그걸 그 달 수익만 빼서 되돌리다 보니 아직 지나지도 않은 미래 달의 수익이
    과거 달의 마감 잔고에 섞여 들어가는 버그가 있었다 (월 경계에서 마감금액 불일치).
    → 전체 거래를 시간순으로 한 번에 순회해서, "오늘 총시드 - 전체 누적수익"이라는
      단 하나의 고정 앵커에서 시작하는 일별 누적 잔고 곡선을 만들고, 그중 요청한 달만
      잘라서 반환하도록 수정. 이러면 모든 달이 같은 기준선을 공유하므로
      월 경계에서도 어제/오늘 잔고가 항상 그날 손익만큼만 차이나게 된다.
    """
    username = get_current_user() or 'guest'
    trades = load_trades(username)
    state = load_state(username)

    target_year_month = f"{year:04d}-{month:02d}"
    current_total_seed = state.get('total_seed', 3000)

    # 전체 거래를 매도시간(exit_time) 기준으로 시간순 정렬
    parsed_trades = []
    for trade in trades:
        try:
            exit_dt = datetime.fromisoformat(trade['exit_time'])
            parsed_trades.append((exit_dt, trade))
        except (ValueError, TypeError, KeyError) as e:
            logger.warning(f"[WARN] 거래 날짜 파싱 실패: {e}")
    parsed_trades.sort(key=lambda x: x[0])

    # 전체 기간 단일 앵커: 오늘 총시드 - 전체 누적수익 = 최초 시작 시드(추정)
    total_all_time_profit = sum(t.get('profit', 0) for _, t in parsed_trades)
    base_initial_seed = current_total_seed - total_all_time_profit

    # 날짜별 통계 + 누적 잔고를 전체 기간에 대해 한 번에 계산 (달마다 따로 역산하지 않음)
    all_daily = {}
    cumulative = 0
    for exit_dt, trade in parsed_trades:
        exit_date = exit_dt.strftime('%Y-%m-%d')
        if exit_date not in all_daily:
            all_daily[exit_date] = {
                'total_trades': 0,
                'win_trades': 0,
                'loss_trades': 0,
                'total_profit': 0,
                'current_seed': 0
            }

        profit = trade.get('profit', 0)
        cumulative += profit
        all_daily[exit_date]['total_trades'] += 1
        all_daily[exit_date]['total_profit'] += profit

        if profit > 0:
            all_daily[exit_date]['win_trades'] += 1
        else:
            all_daily[exit_date]['loss_trades'] += 1

        all_daily[exit_date]['current_seed'] = round(base_initial_seed + cumulative, 2)

    # 요청한 달만 추려서 응답 (기존 응답 형식 유지)
    daily_profit = {d: v for d, v in all_daily.items() if d[:7] == target_year_month}

    profit_before_month = sum(
        v['total_profit'] for d, v in all_daily.items() if d[:7] < target_year_month
    )
    profit_this_month = sum(v['total_profit'] for v in daily_profit.values())

    # 이 달 시작 시드 = 전체 앵커 + 이 달 이전까지의 누적수익
    initial_seed = base_initial_seed + profit_before_month

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
