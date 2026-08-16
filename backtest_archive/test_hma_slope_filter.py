"""
2026-08-14: 사용자 BTC 차트 관찰("HMA200/600 정배열이여도 HMA200 자체는 이미 꺾여서
하락중") 검증 - HMA200 기울기 방향이 신호 방향과 일치하는지 확인하는 필터
(require_hma_slope) 추가 후, 신호 났을때 기울기 불일치면 진입 취소하도록 하여 효과 검증.

스코프: XRP만, 15분봉, 최근 1개월(30일), 서버 기본값(use_hma_regime_filter=True) 기준.
직전에 승인받은 베이스라인 테스트와 동일 스코프 - 베이스라인 대비 slope 필터 추가 효과만 비교.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

SYMBOL = "XRPUSDT"
INTERVAL = "15"
DAYS = 30

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

    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1

    print(f"\n[{label}]")
    print(f"  거래수 {len(trades)}건  승률 {win_rate:.1f}%  PF {pf:.2f}  MDD {mdd:.1f}%  평균보유 {avg_hold:.1f}h")
    print(f"  총수익률(복리) {total_return:+.2f}%")
    print("  종료사유:", ", ".join(f"{k} {v}건({v/len(trades)*100:.1f}%)" for k, v in reasons.items()))


trades_base, seed_base = bcl.run_backtest(candles, use_hma_regime_filter=True)
summarize(trades_base, seed_base, "베이스라인 (기존, slope 필터 없음)")

trades_slope, seed_slope = bcl.run_backtest(candles, use_hma_regime_filter=True, require_hma_slope=True, hma_slope_lookback=5)
summarize(trades_slope, seed_slope, "HMA200 slope 방향 필터 추가 (lookback=5)")
