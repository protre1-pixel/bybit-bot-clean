"""
2026-08-14: 진입필터(HMA200 vs HMA600 정배열)와 0단계(normal) 청산 하드룰(현재가 vs
HMA200 단일선)이 서로 다른 기준을 쓰는 게 "진입 직후 15분만에 즉시손절"의 원인이라는
분석 후, 청산 기준도 진입필터와 동일하게 "HMA200 vs HMA600 정배열"로 맞추면 어떻게
되는지 검증.

스코프: XRP만, 15분봉, 365일(1년치), 진입은 현재 라이브 그대로(use_hma_regime_filter=True),
청산만 기존(가격 vs HMA200) vs 신규(HMA200 vs HMA600 정배열, use_regime_exit=True) 비교.
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

    hma_break = [t for t in trades if t["reason"] == "HMA200 Break"]
    quick = [t for t in hma_break if t["hold_h"] <= 0.26]

    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1

    print(f"\n[{label}]")
    print(f"  거래수 {len(trades)}건  승률 {win_rate:.1f}%  PF {pf:.2f}  MDD {mdd:.1f}%  평균보유 {avg_hold:.1f}h")
    print(f"  총수익률(복리, 참고용) {total_return:+.2f}%")
    print(f"  거래당 평균 raw% {avg_pct:+.3f}%  비복리 단순합산% {sum_pct:+.1f}%")
    print("  종료사유:", ", ".join(f"{k} {v}건({v/len(trades)*100:.1f}%)" for k, v in reasons.items()))
    if hma_break:
        print(f"  HMA200 Break {len(hma_break)}건 중 15분(최소보유)만에 종료: {len(quick)}건 ({len(quick)/len(hma_break)*100:.1f}%)")


trades_base, seed_base = bcl.run_backtest(candles, use_hma_regime_filter=True)
summarize(trades_base, seed_base, "기존 청산 (가격 vs HMA200 단일선)")

trades_regime, seed_regime = bcl.run_backtest(candles, use_hma_regime_filter=True, use_regime_exit=True)
summarize(trades_regime, seed_regime, "신규 청산 (HMA200 vs HMA600 정배열)")
