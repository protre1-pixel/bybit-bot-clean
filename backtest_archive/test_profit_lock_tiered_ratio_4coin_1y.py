"""
2026-08-17(19차): 앞선 테스트들로 확인된 것 -
  1) PROFIT_LOCK_RATIO를 전구간 균일하게 완화(0.7/0.5)하면 4코인 전부 PF/MDD/수익 악화.
  2) 전구간 균일하게 1.0(반납 0%)으로 조이면 4코인 전부 개선(단, 거래수/타이밍은 baseline과
     100% 동일 - 같은 캔들에서 더 좋은 가격에 나갈 뿐, "짧은 눌림에 일찍 잘리는" 문제 자체는
     전혀 해결 안 됨).
  3) trigger_pct를 0.5%→1.0%로 늦춰서 초반 보호를 아예 꺼버리면 4코인 전부 대폭 악화(초반
     구간에서 번 돈을 그대로 반납).

사용자 제안: "구간별로 ratio를 차등 적용해보자" - 최고수익이 아직 작을 때(초반, 눌림 흔한
구간)는 ratio를 느슨하게 줘서 숨 쉴 틈을 주고, 최고수익이 이미 커진 뒤(추세가 확실히 살아있는
후반)는 ratio를 타이트하게(1.0) 조여서 번 돈을 확실히 지키는 방식. backtest_current_live.py에
profit_lock_ratio_tier2_pct/profit_lock_ratio_tier2 파라미터를 신규 추가(peak_profit_pct가
tier2_pct 이상이면 그 순간부터 tier2 ratio로 전환, None이면 기존과 동일 - 하위호환).

트리거(profit_lock_trigger_pct)는 기존 라이브값 0.5%로 고정.

VARIANTS:
  - BASELINE(flat 0.85): 현재 라이브와 동일
  - FLAT_1.0: 전구간 1.0 (참고용, 이미 확인된 최선의 균일값)
  - TIER_A: <2%는 0.7(느슨), >=2%는 1.0(타이트)
  - TIER_B: <3%는 0.6(더 느슨), >=3%는 1.0(타이트)
  - TIER_C: <2%는 0.85(현재와 동일, 초반은 안 건드림), >=2%는 1.0(후반만 추가로 조임)

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
    ("BASELINE(flat 0.85)", dict(profit_lock_ratio=0.85)),
    ("FLAT_1.0", dict(profit_lock_ratio=1.0)),
    ("TIER_A(<2%:0.7,>=2%:1.0)", dict(profit_lock_ratio=0.7, profit_lock_ratio_tier2_pct=2.0, profit_lock_ratio_tier2=1.0)),
    ("TIER_B(<3%:0.6,>=3%:1.0)", dict(profit_lock_ratio=0.6, profit_lock_ratio_tier2_pct=3.0, profit_lock_ratio_tier2=1.0)),
    ("TIER_C(<2%:0.85,>=2%:1.0)", dict(profit_lock_ratio=0.85, profit_lock_ratio_tier2_pct=2.0, profit_lock_ratio_tier2=1.0)),
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

print("\n=== PROFIT LOCK TIERED RATIO 4-COIN 1Y TEST COMPLETE ===", flush=True)
