"""
2026-08-15: 사용자가 SOL 실거래 차트에서 관찰한 문제 - 스퀴즈 선행 없이 갑자기 튀는 진짜
큰 브레이크아웃은 기존 로직(스퀴즈 먼저 감지 → 그 최저점 대비 확장만 breakout으로 인정)이
아예 후보로 못 잡고 놓친 뒤, 가격이 잠깐 눌리며 새로 스퀴즈가 형성된 다음의 작은
재확장에서야(이미 저점/고점 근처) 뒤늦게 추격 진입하는 현상 검증.

`backtest_current_live.py`에 `use_fast_breakout` 실험 파라미터 추가함:
squeeze_status=="normal"이고 스퀴즈 진입 조건도 아닐 때, 폭이 fast_breakout_lookback개
캔들 전 폭 대비 BREAKOUT_MULT(bo)배 이상 급확장되면 스퀴즈 선행 여부와 무관하게 즉시
breakout 후보로 인정(신호판정/필터는 기존 breakout 경로와 100% 동일하게 재사용).

스코프: XRP만, 15분봉, 365일(1년치), sq=0.7/bo=1.6(현재 라이브 기본값),
use_hma_regime_filter=True + profit_lock(0.5/0.85, 현재 라이브 기본값) 동일 조건.
비교: 기존(fast_breakout 없음) vs fast_breakout_lookback=2 vs fast_breakout_lookback=3.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

SYMBOL = "XRPUSDT"
INTERVAL = "15"
DAYS = 365

bcl.SQUEEZE_ENTER_MULT = 0.7
bcl.BREAKOUT_MULT = 1.6
PLT, PLR = 0.5, 0.85

candles = bcl.fetch_klines(SYMBOL, INTERVAL, DAYS)


def summarize(trades, seed_end, label):
    if not trades:
        print(f"\n[{label}] 거래 없음")
        return
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
    avg_pct = sum(t["pct"] for t in trades) / len(trades)
    sum_pct = sum(t["pct"] for t in trades)

    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1

    print(f"\n[{label}]")
    print(f"  거래수 {len(trades)}건  승률 {win_rate:.1f}%  PF {pf:.2f}  MDD {mdd:.1f}%  평균보유 {avg_hold:.1f}h")
    print(f"  총수익률(복리, 참고용) {total_return:+.2f}%")
    print(f"  거래당 평균 raw% {avg_pct:+.3f}%  비복리 단순합산% {sum_pct:+.1f}%")
    print("  종료사유:", ", ".join(f"{k} {v}건({v/len(trades)*100:.1f}%)" for k, v in reasons.items()))


trades_base, seed_base = bcl.run_backtest(
    candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR, use_hma_regime_filter=True)
summarize(trades_base, seed_base, "기존(fast_breakout 없음, 현재 라이브 로직)")

trades_fb2, seed_fb2 = bcl.run_backtest(
    candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR, use_hma_regime_filter=True,
    use_fast_breakout=True, fast_breakout_lookback=2)
summarize(trades_fb2, seed_fb2, "fast_breakout 추가 (lookback=2캔들)")

trades_fb3, seed_fb3 = bcl.run_backtest(
    candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR, use_hma_regime_filter=True,
    use_fast_breakout=True, fast_breakout_lookback=3)
summarize(trades_fb3, seed_fb3, "fast_breakout 추가 (lookback=3캔들)")

print("\n\n=== FAST BREAKOUT XRP 1Y TEST COMPLETE ===", flush=True)
