"""
2026-08-15: 두 가지를 동시에 바꿔서 재검증.

1) 방향 판정: 캔들 몸통(양봉/음봉) 완전히 무시. 브레이크아웃 신호가 뜨면 그 순간 HMA200/600
   정배열(up)이면 롱, 역배열(down)이면 숏으로 방향을 바로 지정 (`use_hma_direction_only=True`,
   기존 파라미터 재사용 - 8/14에 추가했으나 그땐 캔들방향과 섞어서 "실전과 다른 전제"로 참고용
   취급했던 것을 이번엔 명시적으로 단독 검증).

2) 0단계(normal) 청산 기준 변경: 사용자 관찰 - 숏 진입 후 "HMA600 > 가격 > HMA200" 배치가 되면
   (가격이 가까운 200선은 살짝 넘었지만, 먼 600선은 아직 안 넘은 상태) 지금은 "가격 vs HMA200
   단일선"만 보고 15분 만에 바로 손절해버림. 근데 큰 틀(HMA200 vs HMA600 자체의 배열)은 아직
   역배열 그대로 유지 중이니, 이 경우는 즉시 손절하지 말고 계속 들고 가면서(정배열/역배열 자체가
   뒤집힐 때까지) 정리하자는 것 (`use_regime_exit=True`, 8/14에 추가한 기존 파라미터 재사용).

주의: 8/14에 `use_regime_exit=True`를 캔들방향 진입과 조합해서 단독 테스트했을 때 PF 0.35,
MDD 94.5%로 대참사였음 - 원인은 0단계 청산 조건과 "0단계→1단계(trend_follow) 전환" 조건이
둘 다 "HMA200 vs HMA600 정배열"을 쓰게 되면서, 진입 직후 첫 체크에서 전환조건이 먼저 걸려버려
0단계의 빠른 손절 안전장치가 사실상 무력화됐기 때문. 이번엔 방향 판정까지 regime 기반으로
바꾼 상태에서 재확인 - 같은 문제가 재현되는지 명시적으로 확인 목적.

스코프: XRP만, 15분봉, 365일(1년치), sq=0.7/bo=1.6(라이브 동일), profit_lock(0.5/0.85) 유지.
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
summarize(trades1, seed1, "1) 기존 (캔들몸통 방향, 가격vsHMA200 청산) = 현재 라이브")

trades2, seed2 = bcl.run_backtest(
    candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
    use_hma_direction_only=True)
summarize(trades2, seed2, "2) 방향=정배열/역배열(regime), 청산은 기존(가격vsHMA200) 그대로")

trades3, seed3 = bcl.run_backtest(
    candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
    use_regime_exit=True)
summarize(trades3, seed3, "3) 방향은 기존(캔들몸통), 청산=regime(HMA200vs600) [8/14 재확인용]")

trades4, seed4 = bcl.run_backtest(
    candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
    use_hma_direction_only=True, use_regime_exit=True)
summarize(trades4, seed4, "4) 방향=regime + 청산=regime 둘 다 적용 (이번 요청)")

print("\n\n=== REGIME DIRECTION+EXIT XRP 1Y TEST COMPLETE ===", flush=True)
