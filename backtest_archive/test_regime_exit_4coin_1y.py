"""
2026-08-17(7차): XRP 15분봉 1년 테스트에서 use_regime_exit=True(0단계 하드청산을
"가격 vs HMA200 단일선"에서 "HMA200 vs HMA600 정배열이 실제로 뒤집힐 때"로 변경)가
베이스라인 대비 뚜렷하게 개선됨을 확인(승률 63.2%→68.9%, PF 1.35→1.36, 비복리합산
+56.0%→+59.3%, 종료사유 "HMA200 Break" 43건이 전부 사라지고 100% Trend Follow Stop).
사용자 요청으로 다른 코인(BTC/ETH/SOL)에서도 같은 효과가 재현되는지 확인.

trigger/exit 스택은 지금 라이브 그대로(밴드폭 스퀴즈+fast_breakout, HMA 방향판정,
profit_lock+HMA갭 트레일링, stall_exit) 유지한 채 use_regime_exit 하나만 격리 비교.
test_current_live_4coin_2y.py와 동일한 4개 심볼 사용, 기간은 이번 세션 XRP 테스트들과
동일하게 365일(1년)로 맞춤.

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
)


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
    for label, extra in [("BASELINE", dict(use_regime_exit=False)),
                          ("REGIME_EXIT", dict(use_regime_exit=True))]:
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
print("| 심볼 | 조합 | 거래수 | 승률 | PF | MDD | 비복리합산% | 복리(참고) |")
print("|---|---|---|---|---|---|---|---|")
for symbol in SYMBOLS:
    for label in ("BASELINE", "REGIME_EXIT"):
        s = results.get(symbol, {}).get(label)
        if not s:
            print(f"| {symbol} | {label} | - | - | - | - | - | - |")
            continue
        pf_str = f"{s['pf']:.2f}" if s['pf'] != float("inf") else "inf"
        print(f"| {symbol} | {label} | {s['n']} | {s['win_rate']:.1f}% | {pf_str} | {s['mdd']:.1f}% | {s['sum_pct']:+.1f}% | {s['total_return']:+.2f}% |")

print("\n=== REGIME EXIT 4-COIN 1Y TEST COMPLETE ===", flush=True)
