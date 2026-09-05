"""
2026-09-05(40차): "비트코인이 직전 4시간(16캔들) 대비 +-1% 이상 움직였을 때만 (모든 코인,
방향 무관) 진입 허용"이라는 시장 필터를 추가하면 어떨지 사용자가 과감하게 테스트해보자고
요청. BTC가 크게 움직인다 = "장이 활발하다"는 대리지표로 보고, 조용한 횡보 구간엔 아예
신규 진입을 안 하게 막아서 손실 유발 구간을 걸러낼 수 있는지 확인.

정의(AskUserQuestion으로 확정):
- BTC 등락률 = 직전 4시간(16캔들, 15분봉) 종가 대비 현재 종가 등락률
- |등락률| >= 1.0% 이면 그 시각엔 15종 전부(BTC 포함) 롱/숏 무관 진입 허용, 아니면 전부 차단
  (방향 연동 안 함 - "박스권 필터"에 가까움, BTC 방향과 진입 방향을 맞추는 건 아님)

구현: backtest_current_live.py의 run_backtest()에 순수 게이트 파라미터 entry_gate_ts 추가
(2026-09-05, 기존 로직 안 건드림 - 신호가 떠도 해당 시각이 게이트 밖이면 진입만 취소).

비교 대상: 39차(test_live_match_15coin_17d.py)의 "게이트 없음" 기준선(15종, 17일, 현재
라이브 파라미터, n=280, 승률64.6%, PF1.17, 합산 +$1,307.49) 그리고 실제 bot1(n=610,
승률70.8%, PF1.12, +$998.58) 대비 게이트 적용 시 어떻게 달라지는지.

스코프: bot1 실거래 15종, 15분봉, 2026-08-19~2026-09-05(17일), 워밍업 위해 60일치 fetch 후
2026-08-19T15:45:03(UTC) 이후 거래만 집계 (39차와 동일 방법론).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

COINS = ["ADA", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETH",
         "LINK", "LTC", "NEAR", "SOL", "TRX", "XRP"]
INTERVAL = "15"
FETCH_DAYS = 60
EVAL_START_TS = 1787154303000  # bot1 실제 첫 거래 entry_ts (2026-08-19T15:45:03 UTC)
LEVERAGE = 10
SQUEEZE_ENTER_MULT = 0.85
BREAKOUT_MULT = 1.3

BTC_GATE_LOOKBACK = 16  # 4시간 = 16개 15분봉
BTC_GATE_THRESHOLD_PCT = 1.0

bcl.REENTRY_COOLDOWN_MS = 3600 * 1000

LIVE_KWARGS = dict(
    profit_lock_trigger_pct=0.5,
    profit_lock_ratio=0.8,
    use_price_alignment_filter=True,
    stall_exit_candles=8, stall_exit_min_peak_pct=0.5,
    stall_exit_sl_pct=0.4,
    use_hma_direction_only=True,
    use_fast_breakout=True, fast_breakout_lookback=2, fast_breakout_mult=None,
    use_regime_exit=True,
)

# 39차(게이트 없음) 기준값 (test_live_match_15coin_17d.py 결과)
BASELINE_NO_GATE = dict(n=280, win_rate=64.6, pf=1.17, profit=1307.49)
BOT1_REAL = dict(n=610, win_rate=70.8, pf=1.12, profit=998.58)


def summarize(trades):
    if not trades:
        return dict(n=0, win_rate=0, pf=0, profit=0)
    wins = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] <= 0]
    win_rate = len(wins) / len(trades) * 100
    gross_win = sum(t["profit"] for t in wins)
    gross_loss = -sum(t["profit"] for t in losses)
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    profit = sum(t["profit"] for t in trades)
    return dict(n=len(trades), win_rate=win_rate, pf=pf, profit=profit)


bcl.SQUEEZE_ENTER_MULT = SQUEEZE_ENTER_MULT
bcl.BREAKOUT_MULT = BREAKOUT_MULT
bcl.LEVERAGE = LEVERAGE

# ── BTC 등락률 게이트 계산 ──
btc_candles = bcl.fetch_klines("BTCUSDT", INTERVAL, FETCH_DAYS)
entry_gate_ts = set()
gate_open_count = 0
gate_total_count = 0
for i in range(BTC_GATE_LOOKBACK, len(btc_candles)):
    c_now = btc_candles[i]
    if c_now["ts"] < EVAL_START_TS:
        continue
    c_prev = btc_candles[i - BTC_GATE_LOOKBACK]
    pct = (c_now["close"] - c_prev["close"]) / c_prev["close"] * 100
    gate_total_count += 1
    if abs(pct) >= BTC_GATE_THRESHOLD_PCT:
        entry_gate_ts.add(c_now["ts"])
        gate_open_count += 1

print(f"[BTC 게이트] 평가구간 {gate_total_count}개 캔들 중 게이트 열림(|4h등락률|>={BTC_GATE_THRESHOLD_PCT}%): "
      f"{gate_open_count}개 ({gate_open_count/gate_total_count*100:.1f}%)", flush=True)

all_trades = []
results = {}
for coin in COINS:
    symbol = coin + "USDT"
    candles = btc_candles if coin == "BTC" else bcl.fetch_klines(symbol, INTERVAL, FETCH_DAYS)
    trades, seed_end = bcl.run_backtest(candles, entry_sl_cap_pct=None, entry_gate_ts=entry_gate_ts, **LIVE_KWARGS)
    trades = [t for t in trades if t["entry_ts"] >= EVAL_START_TS]
    s = summarize(trades)
    results[coin] = s
    all_trades.extend(trades)
    pfn = f"{s['pf']:.2f}" if s['pf'] != float("inf") else "inf"
    print(f"[{coin:5s}] BTC게이트적용: n={s['n']:3d} 승률={s['win_rate']:5.1f}% PF={pfn:>5s} 수익=${s['profit']:+9.2f}", flush=True)

overall = summarize(all_trades)
pfn = f"{overall['pf']:.2f}" if overall['pf'] != float("inf") else "inf"
print(f"\n{'='*100}")
print(f"[전체] BTC게이트(4h,±1%) 적용: n={overall['n']} 승률={overall['win_rate']:.1f}% PF={pfn} 수익=${overall['profit']:+.2f}")
print(f"[전체] 39차 게이트없음(기준선): n={BASELINE_NO_GATE['n']} 승률={BASELINE_NO_GATE['win_rate']:.1f}% "
      f"PF={BASELINE_NO_GATE['pf']:.2f} 수익=${BASELINE_NO_GATE['profit']:+.2f}")
print(f"[전체] 실제 bot1: n={BOT1_REAL['n']} 승률={BOT1_REAL['win_rate']:.1f}% PF={BOT1_REAL['pf']:.2f} 수익=${BOT1_REAL['profit']:+.2f}")
print("\n=== BTC MOMENTUM GATE TEST (15 COINS, 17 DAYS) COMPLETE ===", flush=True)
