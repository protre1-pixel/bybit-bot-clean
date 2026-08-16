"""
2026-08-15: fast_breakout 테스트에 이어서, 방향 판정 방식 자체를 바꿔보는 추가 실험.

사용자 요청: "캔들이 음봉인지 양봉인지로 롱숏 정하는거 무시하고 200일선만으로 캔들이 위면
롱 아래면 숏으로 정해서" - 정배열/역배열 필터 도입(2026-08-07) 이전, HMA200 단일선 위/아래
위치만으로 방향을 정하던 원래 방식을 재현(`use_price_vs_hma200_direction`, backtest_current_live.py
에 추가함). 기존엔 breakout 캔들의 몸통(양봉/음봉)으로 방향을 먼저 정했음.

스코프: XRP만, 15분봉, 365일(1년치), sq=0.7/bo=1.6(현재 라이브 기본값),
use_hma_regime_filter=True + profit_lock(0.5/0.85) 동일 조건 유지(방향 판정 방식만 교체).
fast_breakout(lookback=2, 어제/오늘 비교에서 PF가 가장 덜 나빠졌던 값)과의 조합도 같이 확인.

4가지 비교:
  1) 기존 (캔들 몸통 방향 + fast_breakout 없음) - 현재 라이브과 동일
  2) 방향만 교체 (가격 vs HMA200) - fast_breakout 없음
  3) fast_breakout(lookback=2)만 추가 - 방향은 캔들 몸통 그대로
  4) fast_breakout(lookback=2) + 방향 교체(가격 vs HMA200) 둘 다 적용
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
    print(f"  거래당 평균 raw% {avg_pct:+.3f}%  비복리 단순합산% {sum_pct:+.1f}%  (복리총수익률 {total_return:+.2f}%, 참고용)")
    print("  종료사유:", ", ".join(f"{k} {v}건({v/len(trades)*100:.1f}%)" for k, v in reasons.items()))


trades1, seed1 = bcl.run_backtest(
    candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR, use_hma_regime_filter=True)
summarize(trades1, seed1, "1) 기존 (캔들몸통 방향, fast_breakout 없음) = 현재 라이브")

trades2, seed2 = bcl.run_backtest(
    candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR, use_hma_regime_filter=True,
    use_price_vs_hma200_direction=True)
summarize(trades2, seed2, "2) 방향 교체(가격 vs HMA200), fast_breakout 없음")

trades3, seed3 = bcl.run_backtest(
    candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR, use_hma_regime_filter=True,
    use_fast_breakout=True, fast_breakout_lookback=2)
summarize(trades3, seed3, "3) fast_breakout(lookback=2)만 추가, 방향은 캔들몸통 그대로")

trades4, seed4 = bcl.run_backtest(
    candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR, use_hma_regime_filter=True,
    use_fast_breakout=True, fast_breakout_lookback=2, use_price_vs_hma200_direction=True)
summarize(trades4, seed4, "4) fast_breakout(lookback=2) + 방향 교체(가격 vs HMA200) 둘 다 적용")

print("\n\n=== PRICE VS HMA200 DIRECTION XRP 1Y TEST COMPLETE ===", flush=True)
