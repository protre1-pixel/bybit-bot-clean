"""
2026-09-05(43차): 42차(test_btc_gate_lookback_sweep_4coin_1y.py)에서 BTC 게이트 lookback을
1시간(4캔들)으로 줄이면 4코인·1년 기준 승률83.1%/PF3.52/MDD21.0%/수익+$110,359로 현재 라이브
(4시간, 승률74.7%/PF1.98/MDD30.3%/+$100,101)보다 전 지표 우월했으나, 게이트 열림이 4.5%
(연 16.5일)뿐이라 4코인 378건이라는 표본으로는 우연 가능성이 남아있다는 우려 제기.
사용자 요청으로 bot1 실거래 15종 전체 x 1년치로 표본을 늘려 1시간 lookback 게이트 있음/없음을
직접 A/B 재검증(41차가 4코인 게이트를 15코인/1년으로 재검증한 것과 동일한 방법론).

정의: BTC 등락률 = 직전 1시간(4캔들, 15분봉) 종가 대비 현재 종가 등락률. |등락률| >= 1.0%
이면 그 시각엔 15종 전부(BTC 포함) 롱/숏 무관 신규 진입 허용, 아니면 전부 차단
(방향 연동 안 함 - 박스권 필터, 기존 게이트 정의와 동일하되 lookback만 16 -> 4).

스코프: bot1 실거래 15종(ADA/ATOM/AVAX/BCH/BNB/BTC/DOGE/DOT/ETH/LINK/LTC/NEAR/SOL/TRX/XRP),
15분봉, 365일, 레버리지 10x, SQ0.85/BO1.3, 현재 라이브 파라미터(41차/42차와 동일 LIVE_KWARGS).

주의: 이 스크립트도 순수 조사용이며, 결과에 따라 자동으로 배포하지 않음(사용자 확인 후 별도 결정).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

COINS = ["ADA", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETH",
         "LINK", "LTC", "NEAR", "SOL", "TRX", "XRP"]
INTERVAL = "15"
DAYS = 365
TEST_LEVERAGE = 10
SQUEEZE_ENTER_MULT = 0.85
BREAKOUT_MULT = 1.3

BTC_GATE_LOOKBACK = 4  # 1시간 = 15분봉 4개
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
for coin in COINS:
    symbol = coin + "USDT"
    candles_by_symbol[coin] = bcl.fetch_klines(symbol, INTERVAL, DAYS)
    print(f"  {symbol}: {len(candles_by_symbol[coin])}개 캔들", flush=True)

btc_candles = candles_by_symbol["BTC"]

# ── BTC 등락률 게이트 계산 (1시간/4캔들, 1년치) ──
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

gate_open_pct = gate_open_count / gate_total_count * 100 if gate_total_count else 0
gate_open_hours = gate_open_count * 15 / 60
print(f"\n[BTC 게이트] 평가구간 {gate_total_count}개 캔들 중 게이트 열림(|1h등락률|>={BTC_GATE_THRESHOLD_PCT}%): "
      f"{gate_open_count}개 ({gate_open_pct:.1f}%, 약 {gate_open_hours:.0f}시간 = {gate_open_hours/24:.1f}일)", flush=True)

all_results = {}  # {coin: {"no_gate": trades, "gated": trades}}

for coin in COINS:
    print(f"\n{'#'*70}\n# {coin}\n{'#'*70}", flush=True)
    candles = candles_by_symbol[coin]

    trades_no_gate, _ = bcl.run_backtest(candles, entry_sl_cap_pct=None, **LIVE_KWARGS)
    trades_gated, _ = bcl.run_backtest(candles, entry_sl_cap_pct=None, entry_gate_ts=entry_gate_ts, **LIVE_KWARGS)

    all_results[coin] = {"no_gate": trades_no_gate, "gated": trades_gated}

    s0 = summarize(trades_no_gate)
    s1 = summarize(trades_gated)
    pfn0 = f"{s0['pf']:.2f}" if s0['pf'] != float("inf") else "inf"
    pfn1 = f"{s1['pf']:.2f}" if s1['pf'] != float("inf") else "inf"
    print(f"[{coin}/게이트없음] n={s0['n']:3d} 승률={s0['win_rate']:5.1f}% PF={pfn0:>5s} "
          f"MDD={s0['mdd']:5.1f}% 수익=${s0['profit']:+9.2f}", flush=True)
    print(f"[{coin}/게이트있음,1h] n={s1['n']:3d} 승률={s1['win_rate']:5.1f}% PF={pfn1:>5s} "
          f"MDD={s1['mdd']:5.1f}% 수익=${s1['profit']:+9.2f}", flush=True)

all_no_gate = []
all_gated = []
for coin in COINS:
    all_no_gate.extend(all_results[coin]["no_gate"])
    all_gated.extend(all_results[coin]["gated"])

all_no_gate.sort(key=lambda t: t["entry_ts"])
all_gated.sort(key=lambda t: t["entry_ts"])

overall_no_gate = summarize(all_no_gate)
overall_gated = summarize(all_gated)
pfn0 = f"{overall_no_gate['pf']:.2f}" if overall_no_gate['pf'] != float("inf") else "inf"
pfn1 = f"{overall_gated['pf']:.2f}" if overall_gated['pf'] != float("inf") else "inf"

print(f"\n{'='*100}")
print(f"[종합 비교표: 15종(bot1 실거래 종목) 1년, SQ0.85/BO1.3, 레버10x, 게이트lookback=1시간]")
print("| 코인 | 게이트 | 거래수 | 승률 | PF | MDD | 수익 |")
print("|---|---|---|---|---|---|---|")
for coin in COINS:
    for label, key in [("없음", "no_gate"), ("있음(1h,±1%)", "gated")]:
        s = summarize(all_results[coin][key])
        pfn = f"{s['pf']:.2f}" if s['pf'] != float("inf") else "inf"
        print(f"| {coin} | {label} | {s['n']} | {s['win_rate']:.1f}% | {pfn} | "
              f"{s['mdd']:.1f}% | ${s['profit']:+.2f} |")

print(f"\n[전체] 게이트없음: n={overall_no_gate['n']} 승률={overall_no_gate['win_rate']:.1f}% "
      f"PF={pfn0} MDD={overall_no_gate['mdd']:.1f}% 수익=${overall_no_gate['profit']:+.2f}")
print(f"[전체] 게이트있음(1h,±1%): n={overall_gated['n']} 승률={overall_gated['win_rate']:.1f}% "
      f"PF={pfn1} MDD={overall_gated['mdd']:.1f}% 수익=${overall_gated['profit']:+.2f}")
print("\n=== BTC GATE 1H LOOKBACK TEST (15 COINS, 1 YEAR) COMPLETE ===", flush=True)
