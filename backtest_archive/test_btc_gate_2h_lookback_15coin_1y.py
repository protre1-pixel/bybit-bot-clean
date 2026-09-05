"""
2026-09-05(45차): 43차(1시간 lookback)/44차(4시간 lookback, 현재라이브)를 15코인·1년
동일조건으로 비교한 결과, 1시간이 승률/PF/MDD/수익 전부 우세하지만 거래수가 1,173건까지
줄어 "거래가 너무 뜸해진다"는 사용자 우려 제기. "확실히 장이 활발한 걸 확인하면서도 거래가
너무 없지는 않을" 중간 지점을 찾기 위해 1시간과 4시간 사이인 2시간(8캔들) lookback을
추가 테스트.

정의: BTC 등락률 = 직전 2시간(8캔들, 15분봉) 종가 대비 현재 종가 등락률(43차/44차와 lookback만
8로 다름, 나머지 방법론/스코프/LIVE_KWARGS 전부 동일). 15분봉 데이터 하나로 계산 - 별도의
"2시간봉"을 받아오는 게 아니라 15분봉 8개 전 종가와 비교하는 방식(사용자 확인 완료).

기존 기준선(43차/44차에서 이미 계산, 재계산 없이 재사용):
- 게이트없음: n=5639, 승률64.9%, PF1.23, MDD44.6%, 수익+$279,988.75
- 게이트있음(1시간): n=1173, 승률81.4%, PF3.30, MDD12.1%, 수익+$372,484.61
- 게이트있음(4시간, 현재라이브): n=2179, 승률73.5%, PF1.95, MDD33.0%, 수익+$362,311.17

주의: 순수 조사용, 자동 배포 없음.
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

BTC_GATE_LOOKBACK = 8  # 2시간 = 15분봉 8개
BTC_GATE_THRESHOLD_PCT = 1.0

BASELINE_NO_GATE = dict(n=5639, win_rate=64.9, pf=1.23, mdd=44.6, profit=279988.75)
BASELINE_1H_GATE = dict(n=1173, win_rate=81.4, pf=3.30, mdd=12.1, profit=372484.61)
BASELINE_4H_GATE = dict(n=2179, win_rate=73.5, pf=1.95, mdd=33.0, profit=362311.17)

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

print("[데이터 fetch(캐시 재사용)]", flush=True)
candles_by_symbol = {}
for coin in COINS:
    symbol = coin + "USDT"
    candles_by_symbol[coin] = bcl.fetch_klines(symbol, INTERVAL, DAYS)
    print(f"  {symbol}: {len(candles_by_symbol[coin])}개 캔들", flush=True)

btc_candles = candles_by_symbol["BTC"]

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
print(f"\n[BTC 게이트] 평가구간 {gate_total_count}개 캔들 중 게이트 열림(|2h등락률|>={BTC_GATE_THRESHOLD_PCT}%): "
      f"{gate_open_count}개 ({gate_open_pct:.1f}%, 약 {gate_open_hours:.0f}시간 = {gate_open_hours/24:.1f}일)", flush=True)

all_gated = []
for coin in COINS:
    candles = candles_by_symbol[coin]
    trades_gated, _ = bcl.run_backtest(candles, entry_sl_cap_pct=None, entry_gate_ts=entry_gate_ts, **LIVE_KWARGS)
    all_gated.extend(trades_gated)
    s1 = summarize(trades_gated)
    pfn1 = f"{s1['pf']:.2f}" if s1['pf'] != float("inf") else "inf"
    print(f"[{coin}/게이트있음,2h] n={s1['n']:3d} 승률={s1['win_rate']:5.1f}% PF={pfn1:>5s} "
          f"MDD={s1['mdd']:5.1f}% 수익=${s1['profit']:+9.2f}", flush=True)

all_gated.sort(key=lambda t: t["entry_ts"])
overall_gated = summarize(all_gated)
pfn1 = f"{overall_gated['pf']:.2f}" if overall_gated['pf'] != float("inf") else "inf"

print(f"\n{'='*100}")
print(f"[종합 비교표: 15종(bot1 실거래 종목) 1년, SQ0.85/BO1.3, 레버10x]")
print("| 항목 | 거래수 | 승률 | PF | MDD | 수익 |")
print("|---|---|---|---|---|---|")
print(f"| 게이트없음 | {BASELINE_NO_GATE['n']} | {BASELINE_NO_GATE['win_rate']:.1f}% | "
      f"{BASELINE_NO_GATE['pf']:.2f} | {BASELINE_NO_GATE['mdd']:.1f}% | ${BASELINE_NO_GATE['profit']:+.2f} |")
print(f"| 게이트있음(1시간) | {BASELINE_1H_GATE['n']} | {BASELINE_1H_GATE['win_rate']:.1f}% | "
      f"{BASELINE_1H_GATE['pf']:.2f} | {BASELINE_1H_GATE['mdd']:.1f}% | ${BASELINE_1H_GATE['profit']:+.2f} |")
print(f"| 게이트있음(2시간, 신규) | {overall_gated['n']} | {overall_gated['win_rate']:.1f}% | "
      f"{pfn1} | {overall_gated['mdd']:.1f}% | ${overall_gated['profit']:+.2f} |")
print(f"| 게이트있음(4시간,현재라이브) | {BASELINE_4H_GATE['n']} | {BASELINE_4H_GATE['win_rate']:.1f}% | "
      f"{BASELINE_4H_GATE['pf']:.2f} | {BASELINE_4H_GATE['mdd']:.1f}% | ${BASELINE_4H_GATE['profit']:+.2f} |")

print("\n=== BTC GATE 2H LOOKBACK TEST (15 COINS, 1 YEAR) COMPLETE ===", flush=True)
