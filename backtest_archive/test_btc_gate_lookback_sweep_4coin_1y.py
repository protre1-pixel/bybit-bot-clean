"""
2026-09-05(42차): 41차(test_btc_momentum_gate_4coin_1y.py)에서 검증한 "BTC 직전 4시간
(16캔들) 등락률 |1%| 게이트"가 실거래(bot1/bot2)에 배포된 직후, 사용자가 "lookback을
1시간이나 12시간/24시간(일봉)으로 바꾸면 결과가 달라지냐"는 궁금증 제기 → lookback
윈도우만 바꿔가며(임계값은 동일 1.0%로 고정) 스윕 비교.

주의: 이 스크립트는 순수 조사용이며, 결과에 따라 자동으로 배포하지 않음(사용자 확인 후
별도 결정).

정의: 각 lookback(L캔들, 15분봉) 마다 "직전 L캔들 전 종가 대비 현재 종가 등락률 |1.0%|
이상"이면 게이트 열림 - 41차와 동일한 방향무관(박스권) 필터, lookback만 가변.

스코프: BTCUSDT/ETHUSDT/XRPUSDT/SOLUSDT, 15분봉, 365일, 레버리지 10x, SQ0.85/BO1.3,
현재 라이브 파라미터(41차와 동일 LIVE_KWARGS). 41차의 "게이트없음" 결과(n=1585, 승률62.4%,
PF1.08, MDD69.2%, 수익+$7,263.88)를 공통 기준선으로 재사용(하드코딩, 재계산 안 함 -
게이트 유무 자체는 이미 41차에서 검증됨, 이번엔 lookback 값 자체의 민감도만 확인).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT"]
INTERVAL = "15"
DAYS = 365
TEST_LEVERAGE = 10
SQUEEZE_ENTER_MULT = 0.85
BREAKOUT_MULT = 1.3

BTC_GATE_THRESHOLD_PCT = 1.0
LOOKBACKS = {
    "1시간(4캔들)": 4,
    "4시간(16캔들, 현재라이브)": 16,
    "12시간(48캔들)": 48,
    "24시간/일봉(96캔들)": 96,
}

# 41차 게이트없음 기준선 (재계산 없이 재사용)
BASELINE_NO_GATE = dict(n=1585, win_rate=62.4, pf=1.08, mdd=69.2, profit=7263.88)

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


def summarize(trades):
    if not trades:
        return dict(n=0, win_rate=0, pf=0, mdd=0, profit=0)
    wins = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] <= 0]
    win_rate = len(wins) / len(trades) * 100
    gross_win = sum(t["profit"] for t in wins)
    gross_loss = -sum(t["profit"] for t in losses)
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")

    equity = [bcl.SEED]
    run = bcl.SEED
    for t in trades:
        run += t["profit"]
        equity.append(run)
    peak = equity[0]
    mdd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = (peak - e) / peak * 100 if peak > 0 else 0
        if dd > mdd:
            mdd = dd

    profit = sum(t["profit"] for t in trades)
    return dict(n=len(trades), win_rate=win_rate, pf=pf, mdd=mdd, profit=profit)


bcl.SQUEEZE_ENTER_MULT = SQUEEZE_ENTER_MULT
bcl.BREAKOUT_MULT = BREAKOUT_MULT
bcl.LEVERAGE = TEST_LEVERAGE

print("[데이터 fetch]", flush=True)
candles_by_symbol = {}
for symbol in SYMBOLS:
    candles_by_symbol[symbol] = bcl.fetch_klines(symbol, INTERVAL, DAYS)
    print(f"  {symbol}: {len(candles_by_symbol[symbol])}개 캔들", flush=True)

btc_candles = candles_by_symbol["BTCUSDT"]

sweep_results = {}  # {lookback_label: {"gate_open_pct":..., "per_symbol":{...}, "overall":{...}}}

for label, lookback in LOOKBACKS.items():
    print(f"\n{'#'*70}\n# lookback={label} ({lookback}캔들)\n{'#'*70}", flush=True)

    entry_gate_ts = set()
    gate_open_count = 0
    gate_total_count = 0
    for i in range(lookback, len(btc_candles)):
        c_now = btc_candles[i]
        c_prev = btc_candles[i - lookback]
        pct = (c_now["close"] - c_prev["close"]) / c_prev["close"] * 100
        gate_total_count += 1
        if abs(pct) >= BTC_GATE_THRESHOLD_PCT:
            entry_gate_ts.add(c_now["ts"])
            gate_open_count += 1
    gate_open_pct = gate_open_count / gate_total_count * 100 if gate_total_count else 0
    print(f"[게이트] 평가구간 {gate_total_count}개 캔들 중 열림: {gate_open_count}개 ({gate_open_pct:.1f}%)", flush=True)

    per_symbol = {}
    all_trades = []
    for symbol in SYMBOLS:
        candles = candles_by_symbol[symbol]
        trades, _ = bcl.run_backtest(candles, entry_sl_cap_pct=None, entry_gate_ts=entry_gate_ts, **LIVE_KWARGS)
        s = summarize(trades)
        per_symbol[symbol] = s
        all_trades.extend(trades)
        pfn = f"{s['pf']:.2f}" if s['pf'] != float("inf") else "inf"
        print(f"  [{symbol}] n={s['n']:3d} 승률={s['win_rate']:5.1f}% PF={pfn:>5s} "
              f"MDD={s['mdd']:5.1f}% 수익=${s['profit']:+9.2f}", flush=True)

    all_trades.sort(key=lambda t: t["entry_ts"])
    overall = summarize(all_trades)
    sweep_results[label] = dict(gate_open_pct=gate_open_pct, per_symbol=per_symbol, overall=overall)
    pfn = f"{overall['pf']:.2f}" if overall['pf'] != float("inf") else "inf"
    print(f"  [전체] n={overall['n']} 승률={overall['win_rate']:.1f}% PF={pfn} "
          f"MDD={overall['mdd']:.1f}% 수익=${overall['profit']:+.2f}", flush=True)

print(f"\n{'='*100}")
print("[종합 비교: lookback 스윕, 임계값 |1.0%| 고정, BTC/ETH/XRP/SOL 1년]")
print("| lookback | 게이트열림% | 거래수 | 승률 | PF | MDD | 수익 |")
print("|---|---|---|---|---|---|---|")
print(f"| (게이트없음, 41차 기준선) | 100.0% | {BASELINE_NO_GATE['n']} | "
      f"{BASELINE_NO_GATE['win_rate']:.1f}% | {BASELINE_NO_GATE['pf']:.2f} | "
      f"{BASELINE_NO_GATE['mdd']:.1f}% | ${BASELINE_NO_GATE['profit']:+.2f} |")
for label in LOOKBACKS:
    r = sweep_results[label]
    o = r["overall"]
    pfn = f"{o['pf']:.2f}" if o['pf'] != float("inf") else "inf"
    print(f"| {label} | {r['gate_open_pct']:.1f}% | {o['n']} | {o['win_rate']:.1f}% | "
          f"{pfn} | {o['mdd']:.1f}% | ${o['profit']:+.2f} |")

print("\n=== BTC GATE LOOKBACK SWEEP (4 COINS, 1 YEAR) COMPLETE ===", flush=True)
