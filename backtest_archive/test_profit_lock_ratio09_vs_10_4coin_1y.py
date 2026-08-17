"""
2026-08-17(20차): 19차 테스트(TIER 실험)에서 trigger=0.5% 고정 기준으로 FLAT_1.0(반납 0%,
전구간 균일)이 BASELINE(0.85)/TIER_A/TIER_B/TIER_C를 전부 이기고 가장 좋았음(4코인 전부).

사용자 질문: 그럼 1.0(완전 무반납)과 0.9(아주 살짝만 반납 허용) 중에 뭐가 더 나은지 직접
비교해보자는 요청. 나머지 조건(trigger=0.5%, stall_exit, fast_breakout, price_alignment_filter,
regime_exit 등 현재 라이브와 동일한 풀 콤보)은 19차와 동일하게 고정하고 profit_lock_ratio만
0.9 vs 1.0 두 값으로 비교.

스코프: BTCUSDT/ETHUSDT/XRPUSDT/SOLUSDT, 15분봉, 365일치.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT"]
INTERVAL = "15"
DAYS = 365
TRIGGER = 0.5
STALL_CANDLES = 8
STALL_MIN_PEAK = 0.5
STALL_SL_PCT = 0.4

base_kwargs = dict(
    profit_lock_trigger_pct=TRIGGER,
    use_price_alignment_filter=True,
    stall_exit_candles=STALL_CANDLES, stall_exit_min_peak_pct=STALL_MIN_PEAK,
    stall_exit_sl_pct=STALL_SL_PCT,
    use_hma_direction_only=True,
    use_fast_breakout=True, fast_breakout_lookback=2, fast_breakout_mult=None,
    use_regime_exit=True,
)

VARIANTS = [
    ("RATIO_0.9", dict(profit_lock_ratio=0.9)),
    ("RATIO_1.0", dict(profit_lock_ratio=1.0)),
]


def summarize(trades, seed_end):
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

    avg_hold = sum(t["hold_h"] for t in trades) / len(trades)
    total_return = (seed_end - bcl.SEED) / bcl.SEED * 100
    sum_pct = sum(t["pct"] for t in trades)

    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1

    return dict(n=len(trades), win_rate=win_rate, pf=pf, mdd=mdd, avg_hold=avg_hold,
                sum_pct=sum_pct, total_return=total_return, reasons=reasons)


results = {}

for symbol in SYMBOLS:
    bcl.SQUEEZE_ENTER_MULT = 0.7
    bcl.BREAKOUT_MULT = 1.6
    candles = bcl.fetch_klines(symbol, INTERVAL, DAYS)

    print(f"\n{'#'*60}\n# {symbol}\n{'#'*60}")
    results[symbol] = {}
    for label, extra in VARIANTS:
        kwargs = dict(base_kwargs, **extra)
        trades, seed_end = bcl.run_backtest(candles, **kwargs)
        if not trades:
            print(f"[{symbol}/{label}] 거래 없음")
            continue
        s = summarize(trades, seed_end)
        results[symbol][label] = s
        print(f"[{symbol}/{label}] 거래수 {s['n']}건  승률 {s['win_rate']:.1f}%  PF {s['pf']:.2f}  "
              f"MDD {s['mdd']:.1f}%  평균보유 {s['avg_hold']:.1f}h  비복리합산 {s['sum_pct']:+.1f}%  "
              f"복리(참고) {s['total_return']:+.2f}%")
        print("  종료사유:", ", ".join(f"{k} {v}건({v/s['n']*100:.1f}%)" for k, v in s["reasons"].items()))

print(f"\n{'='*70}\n[종합 비교표]\n{'='*70}")
print("| 심볼 | 조합 | 거래수 | 승률 | PF | MDD | 비복리합산% | 복리(참고) | 평균보유h |")
print("|---|---|---|---|---|---|---|---|---|")
for symbol in SYMBOLS:
    for label, extra in VARIANTS:
        s = results.get(symbol, {}).get(label)
        if not s:
            print(f"| {symbol} | {label} | - | - | - | - | - | - | - |")
            continue
        pf_str = f"{s['pf']:.2f}" if s['pf'] != float("inf") else "inf"
        print(f"| {symbol} | {label} | {s['n']} | {s['win_rate']:.1f}% | {pf_str} | {s['mdd']:.1f}% | "
              f"{s['sum_pct']:+.1f}% | {s['total_return']:+.2f}% | {s['avg_hold']:.1f} |")

print("\n=== PROFIT LOCK RATIO 0.9 vs 1.0 4-COIN 1Y TEST COMPLETE ===", flush=True)
