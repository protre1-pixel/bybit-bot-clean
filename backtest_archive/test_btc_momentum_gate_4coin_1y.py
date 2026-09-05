"""
2026-09-05(41차): 40차(15종, 17일)에서 "BTC 직전 4시간(16캔들) 등락률 |1%| 이상일 때만
전체 코인 진입 허용" 게이트가 n=158(-44%) 대신 PF 1.17->2.60, 수익 +$1,307->+$4,584로
크게 개선된 결과가 나왔으나, 17일/코인당 5~15건이라는 작은 표본이라 우연일 가능성을
배제할 수 없음. 사용자 요청으로 표본을 늘려 재검증: 38차(SL캡 MAE 분석)에서 이미 쓴
BTC/ETH/XRP/SOL 1년치 데이터에 동일한 게이트를 걸어 게이트 있음/없음을 직접 A/B 비교.

정의(40차와 동일, AskUserQuestion으로 확정된 사양 재사용):
- BTC 등락률 = 직전 4시간(16캔들, 15분봉) 종가 대비 현재 종가 등락률
- |등락률| >= 1.0% 이면 그 시각엔 대상 코인 전부(BTC 포함) 롱/숏 무관 진입 허용, 아니면 차단
  (방향 연동 안 함 - BTC 방향과 진입 방향을 맞추는 게 아니라 "박스권 필터")

방법: 같은 종목·같은 기간 데이터에 대해 entry_gate_ts=None(게이트 없음, 현재 라이브와 동일)
vs entry_gate_ts=<계산된 집합>(게이트 있음) 두 번 백테스트해서 직접 비교(외부 하드코딩
기준값 없이 스크립트 내에서 자체 A/B).

스코프: BTCUSDT/ETHUSDT/XRPUSDT/SOLUSDT, 15분봉, 365일, 레버리지 10x, SQ0.85/BO1.3,
현재 라이브 파라미터(38차 test_sl_cap_mae_4coin_1y.py와 동일 LIVE_KWARGS).
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

BTC_GATE_LOOKBACK = 16  # 4시간 = 16개 15분봉
BTC_GATE_THRESHOLD_PCT = 1.0

bcl.REENTRY_COOLDOWN_MS = 3600 * 1000  # 1시간 (2026-08-19 라이브 변경분)

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
        return dict(n=0, win_rate=0, pf=0, mdd=0, sum_pct=0, profit=0)
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

    sum_pct = sum(t["pct"] for t in trades)
    profit = sum(t["profit"] for t in trades)
    return dict(n=len(trades), win_rate=win_rate, pf=pf, mdd=mdd, sum_pct=sum_pct, profit=profit)


bcl.SQUEEZE_ENTER_MULT = SQUEEZE_ENTER_MULT
bcl.BREAKOUT_MULT = BREAKOUT_MULT
bcl.LEVERAGE = TEST_LEVERAGE

# ── BTC 등락률 게이트 계산 (1년치) ──
btc_candles = bcl.fetch_klines("BTCUSDT", INTERVAL, DAYS)
entry_gate_ts = set()
gate_open_count = 0
gate_total_count = 0
for i in range(BTC_GATE_LOOKBACK, len(btc_candles)):
    c_now = btc_candles[i]
    c_prev = btc_candles[i - BTC_GATE_LOOKBACK]
    pct = (c_now["close"] - c_prev["close"]) / c_prev["close"] * 100
    gate_total_count += 1
    if abs(pct) >= BTC_GATE_THRESHOLD_PCT:
        entry_gate_ts.add(c_now["ts"])
        gate_open_count += 1

print(f"[BTC 게이트] 평가구간 {gate_total_count}개 캔들 중 게이트 열림(|4h등락률|>={BTC_GATE_THRESHOLD_PCT}%): "
      f"{gate_open_count}개 ({gate_open_count/gate_total_count*100:.1f}%)", flush=True)

all_results = {}  # {symbol: {"no_gate": trades, "gated": trades}}

for symbol in SYMBOLS:
    print(f"\n{'#'*70}\n# {symbol}\n{'#'*70}", flush=True)
    candles = btc_candles if symbol == "BTCUSDT" else bcl.fetch_klines(symbol, INTERVAL, DAYS)

    trades_no_gate, _ = bcl.run_backtest(candles, entry_sl_cap_pct=None, **LIVE_KWARGS)
    trades_gated, _ = bcl.run_backtest(candles, entry_sl_cap_pct=None, entry_gate_ts=entry_gate_ts, **LIVE_KWARGS)

    all_results[symbol] = {"no_gate": trades_no_gate, "gated": trades_gated}

    s0 = summarize(trades_no_gate)
    s1 = summarize(trades_gated)
    pfn0 = f"{s0['pf']:.2f}" if s0['pf'] != float("inf") else "inf"
    pfn1 = f"{s1['pf']:.2f}" if s1['pf'] != float("inf") else "inf"
    print(f"[{symbol}/게이트없음] n={s0['n']:3d} 승률={s0['win_rate']:5.1f}% PF={pfn0:>5s} "
          f"MDD={s0['mdd']:5.1f}% 수익=${s0['profit']:+9.2f}", flush=True)
    print(f"[{symbol}/게이트있음] n={s1['n']:3d} 승률={s1['win_rate']:5.1f}% PF={pfn1:>5s} "
          f"MDD={s1['mdd']:5.1f}% 수익=${s1['profit']:+9.2f}", flush=True)

all_no_gate = []
all_gated = []
for symbol in SYMBOLS:
    all_no_gate.extend(all_results[symbol]["no_gate"])
    all_gated.extend(all_results[symbol]["gated"])

# MDD/equity curve는 시간순이어야 의미가 있으므로, 4개 심볼 거래를 하나의 공유계좌로
# 가정하고 entry_ts 기준으로 정렬 후 합산(각 심볼별 MDD는 위에서 이미 개별 출력함).
all_no_gate.sort(key=lambda t: t["entry_ts"])
all_gated.sort(key=lambda t: t["entry_ts"])

overall_no_gate = summarize(all_no_gate)
overall_gated = summarize(all_gated)
pfn0 = f"{overall_no_gate['pf']:.2f}" if overall_no_gate['pf'] != float("inf") else "inf"
pfn1 = f"{overall_gated['pf']:.2f}" if overall_gated['pf'] != float("inf") else "inf"

print(f"\n{'='*100}")
print(f"[종합 비교표: BTC/ETH/XRP/SOL 1년, SQ0.85/BO1.3, 레버10x]")
print("| 심볼 | 게이트 | 거래수 | 승률 | PF | MDD | 수익 |")
print("|---|---|---|---|---|---|---|")
for symbol in SYMBOLS:
    for label, key in [("없음", "no_gate"), ("있음(4h,±1%)", "gated")]:
        s = summarize(all_results[symbol][key])
        pfn = f"{s['pf']:.2f}" if s['pf'] != float("inf") else "inf"
        print(f"| {symbol} | {label} | {s['n']} | {s['win_rate']:.1f}% | {pfn} | "
              f"{s['mdd']:.1f}% | ${s['profit']:+.2f} |")

print(f"\n[전체] 게이트없음: n={overall_no_gate['n']} 승률={overall_no_gate['win_rate']:.1f}% "
      f"PF={pfn0} MDD={overall_no_gate['mdd']:.1f}% 수익=${overall_no_gate['profit']:+.2f}")
print(f"[전체] 게이트있음(4h,±1%): n={overall_gated['n']} 승률={overall_gated['win_rate']:.1f}% "
      f"PF={pfn1} MDD={overall_gated['mdd']:.1f}% 수익=${overall_gated['profit']:+.2f}")
print("\n=== BTC MOMENTUM GATE TEST (4 COINS, 1 YEAR) COMPLETE ===", flush=True)
