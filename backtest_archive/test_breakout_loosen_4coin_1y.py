"""
2026-08-17(11차): 직전 XRP 단일 테스트(test_breakout_loosen_xrp_1y.py)에서 BREAKOUT_MULT를
라이브값 1.6에서 1.4로 낮추면(더 쉽게 브레이크아웃 인정 = 진입 완화) 승률/PF는 거의
유지하면서 거래수·비복리합산 수익이 늘어나는 걸 확인(단, MDD는 37.6%→46.4%로 악화).
사용자 요청으로 이 bo=1.4가 XRP만의 우연인지 다른 코인(BTC/ETH/SOL)에서도 재현되는지 확인.

SQUEEZE_ENTER_MULT는 라이브 값(0.7) 그대로 고정, BREAKOUT_MULT만 라이브(1.6) vs 완화(1.4)
2가지로 격리 비교. exit/방향판정 스택은 라이브 그대로(profit_lock+HMA갭 트레일링,
stall_exit, use_hma_direction_only, fast_breakout), use_regime_exit=False(라이브 미반영
실험옵션이므로 비활성 유지).

test_current_live_4coin_2y.py / test_regime_exit_4coin_1y.py와 동일한 4개 심볼 사용,
기간은 이번 세션 XRP 테스트들과 동일하게 365일(1년)로 맞춤.

스코프: BTCUSDT, ETHUSDT, XRPUSDT, SOLUSDT. 15분봉, 365일치.
"""
import sys
import os
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT"]
INTERVAL = "15"
DAYS = 365
PLT, PLR = 0.5, 0.85
STALL_CANDLES = 8
STALL_MIN_PEAK = 0.5
STALL_SL_PCT = 0.4

base_kwargs = dict(
    profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
    use_price_alignment_filter=True,
    stall_exit_candles=STALL_CANDLES, stall_exit_min_peak_pct=STALL_MIN_PEAK,
    stall_exit_sl_pct=STALL_SL_PCT,
    use_hma_direction_only=True,
    use_fast_breakout=True, fast_breakout_lookback=2, fast_breakout_mult=None,
    use_regime_exit=False,
)

VARIANTS = [
    ("LIVE", 0.7, 1.6),
    ("BO_1.4", 0.7, 1.4),
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
    print(f"\n{'#'*60}\n# {symbol}\n{'#'*60}")
    results[symbol] = {}
    bcl.SQUEEZE_ENTER_MULT = 0.7
    bcl.BREAKOUT_MULT = 1.6
    candles = bcl.fetch_klines(symbol, INTERVAL, DAYS)

    for label, sq_mult, bo_mult in VARIANTS:
        bcl.SQUEEZE_ENTER_MULT = sq_mult
        bcl.BREAKOUT_MULT = bo_mult
        trades, seed_end = bcl.run_backtest(candles, **base_kwargs)
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
print("| 심볼 | 조합 | 거래수 | 승률 | PF | MDD | 비복리합산% | 복리(참고) |")
print("|---|---|---|---|---|---|---|---|")
for symbol in SYMBOLS:
    for label, _, _ in VARIANTS:
        s = results.get(symbol, {}).get(label)
        if not s:
            print(f"| {symbol} | {label} | - | - | - | - | - | - |")
            continue
        pf_str = f"{s['pf']:.2f}" if s['pf'] != float("inf") else "inf"
        print(f"| {symbol} | {label} | {s['n']} | {s['win_rate']:.1f}% | {pf_str} | {s['mdd']:.1f}% | {s['sum_pct']:+.1f}% | {s['total_return']:+.2f}% |")

print("\n=== BREAKOUT LOOSEN 4-COIN 1Y TEST COMPLETE ===", flush=True)
