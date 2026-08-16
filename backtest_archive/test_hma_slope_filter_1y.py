"""
2026-08-14: HMA200 slope 방향 필터(require_hma_slope) 1년치 재검증.
스코프: XRP만, 15분봉, 365일, use_hma_regime_filter=True(실전 로직) 기준,
slope 필터 없음 vs 있음(lookback=5) 비교.

1년치는 복리 총수익률이 거래횟수 차이에 지수적으로 좌우돼 의미가 왜곡되는 문제가
이전 세션에서 확인됐으므로(2026-08-14_hma_gap_threshold.md 3번 참고), PF/MDD/승률과
더불어 "거래 1건당 평균 raw% 수익률", "비복리 단순합산%"도 같이 출력.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

SYMBOL = "XRPUSDT"
INTERVAL = "15"
DAYS = 365

candles = bcl.fetch_klines(SYMBOL, INTERVAL, DAYS)


def summarize(trades, seed_end, label):
    if not trades:
        print(f"[{label}] 거래 없음")
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


trades_base, seed_base = bcl.run_backtest(candles, use_hma_regime_filter=True)
summarize(trades_base, seed_base, "베이스라인 (기존, slope 필터 없음)")

trades_slope, seed_slope = bcl.run_backtest(candles, use_hma_regime_filter=True, require_hma_slope=True, hma_slope_lookback=5)
summarize(trades_slope, seed_slope, "HMA200 slope 방향 필터 추가 (lookback=5)")
