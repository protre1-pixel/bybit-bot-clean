"""
2026-08-17(14차): 사용자가 실거래 차트(뚜렷한 우상향 추세, HMA200/600 정배열 살아있는 상태에서
짧은 눌림이 여러 번 나오는 구간)를 보여주며 "추세가 안 죽었는데도 짧은 눌림에 자꾸 팔린다"는
문제제기. 원인 조사 결과 - 0단계(normal)는 8/17에 이미 "정배열 자체가 뒤집혀야만 청산"으로
고쳐놨지만(use_regime_exit), 1단계(trend_follow, 정작 수익이 나서 더 크게 먹어야 할 구간)는
아직 손 안 댐: 여기는 "HMA갭이 진입후 최댓값(gap_peak) 대비 HMA_GAP_CONTRACTION_RATIO(0.4) 밑으로
"수축"만 해도(실제 반전 전에!) SL을 최고점 근처로 확 당겨버리는(HMA_GAP_EXIT_BUFFER_PCT=0.6%)
별도의 더 예민한 트레일링이 살아있음. 완전 반전(HMA Trend Reversal, gap 부호 자체가 뒤집힘)은
이 수축 트레일링과 별개로 여전히 살아있어 계속 최종 안전장치 역할.

이 수축 트레일링을 완화/제거하는 3가지 방향을 베이스라인과 비교:
  BASELINE: 현재 라이브(ratio=0.4, buffer=0.6%) - use_regime_exit=True 포함, 8/17 배포 상태 그대로
  A_DISABLE: 수축 트레일링 완전 제거(ratio=0.0 → gap_abs(항상 >=0)가 gap_peak*0(=0)보다 작아지는
    경우가 없어 조건 자체가 절대 안 걸림). trend_follow 단계 청산은 오직 완전반전(HMA Trend
    Reversal)과 profit_lock 래칫(최고수익×0.85 방어선)만 남음 - 사용자 취지("정배열 안 깨지면
    쭉 간다")에 가장 가까운 극단
  B_LOOSER_RATIO: 반응 민감도만 완화(ratio 0.4→0.2, 최댓값 대비 80% 밑으로 줄어야 반응 - 더 깊이
    눌려야 신호가 뜸). buffer는 그대로.
  C_LOOSER_BUFFER: 신호가 뜨는 시점은 그대로 두되(ratio 0.4 유지), 신호 뜬 후 SL을 최고점에서
    떨어뜨리는 여유폭만 완화(buffer 0.6%→1.2%, 신호 후에도 숨쉴 틈을 더 줌)

HMA_GAP_CONTRACTION_RATIO/HMA_GAP_EXIT_BUFFER_PCT는 backtest_current_live.py 모듈 전역 상수라
함수 인자가 아님 - bcl.<상수명> 직접 덮어써서 각 variant 실행 전에 세팅.

use_regime_exit=True(8/17 배포된 라이브 상태) 포함, 나머지 스택(진입필터/방향판정/fast_breakout/
profit_lock/stall_exit)은 전부 라이브 그대로 고정. sq/bo는 라이브 기본값(0.7/1.6) 고정.

스코프: BTCUSDT/ETHUSDT/XRPUSDT/SOLUSDT, 15분봉, 365일치.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT"]
INTERVAL = "15"
DAYS = 365
PLT, PLR = 0.5, 0.85
STALL_CANDLES = 8
STALL_MIN_PEAK = 0.5
STALL_SL_PCT = 0.4

BASE_RATIO = 0.4
BASE_BUFFER = 0.6

base_kwargs = dict(
    profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
    use_price_alignment_filter=True,
    stall_exit_candles=STALL_CANDLES, stall_exit_min_peak_pct=STALL_MIN_PEAK,
    stall_exit_sl_pct=STALL_SL_PCT,
    use_hma_direction_only=True,
    use_fast_breakout=True, fast_breakout_lookback=2, fast_breakout_mult=None,
    use_regime_exit=True,
)

VARIANTS = [
    ("BASELINE", 0.4, 0.6),
    ("A_DISABLE", 0.0, 0.6),
    ("B_LOOSER_RATIO", 0.2, 0.6),
    ("C_LOOSER_BUFFER", 0.4, 1.2),
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
    for label, ratio, buffer in VARIANTS:
        bcl.HMA_GAP_CONTRACTION_RATIO = ratio
        bcl.HMA_GAP_EXIT_BUFFER_PCT = buffer
        trades, seed_end = bcl.run_backtest(candles, **base_kwargs)
        if not trades:
            print(f"[{symbol}/{label}] 거래 없음")
            continue
        s = summarize(trades, seed_end)
        results[symbol][label] = s
        print(f"[{symbol}/{label} ratio={ratio} buffer={buffer}] 거래수 {s['n']}건  승률 {s['win_rate']:.1f}%  "
              f"PF {s['pf']:.2f}  MDD {s['mdd']:.1f}%  평균보유 {s['avg_hold']:.1f}h  "
              f"비복리합산 {s['sum_pct']:+.1f}%  복리(참고) {s['total_return']:+.2f}%")
        print("  종료사유:", ", ".join(f"{k} {v}건({v/s['n']*100:.1f}%)" for k, v in s["reasons"].items()))

# 원상복구(다른 스크립트에 영향 안 주도록)
bcl.HMA_GAP_CONTRACTION_RATIO = BASE_RATIO
bcl.HMA_GAP_EXIT_BUFFER_PCT = BASE_BUFFER

print(f"\n{'='*70}\n[종합 비교표]\n{'='*70}")
print("| 심볼 | 조합 | 거래수 | 승률 | PF | MDD | 비복리합산% | 복리(참고) | 평균보유h |")
print("|---|---|---|---|---|---|---|---|---|")
for symbol in SYMBOLS:
    for label, ratio, buffer in VARIANTS:
        s = results.get(symbol, {}).get(label)
        if not s:
            print(f"| {symbol} | {label} | - | - | - | - | - | - | - |")
            continue
        pf_str = f"{s['pf']:.2f}" if s['pf'] != float("inf") else "inf"
        print(f"| {symbol} | {label} | {s['n']} | {s['win_rate']:.1f}% | {pf_str} | {s['mdd']:.1f}% | "
              f"{s['sum_pct']:+.1f}% | {s['total_return']:+.2f}% | {s['avg_hold']:.1f} |")

print("\n=== TREND FOLLOW TRAIL LOOSEN 4-COIN 1Y TEST COMPLETE ===", flush=True)
