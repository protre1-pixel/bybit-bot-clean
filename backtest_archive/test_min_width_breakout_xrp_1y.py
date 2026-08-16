"""
2026-08-16: 2candle_breakout(직전 봉 1개 대비 2.5배)이 1년에 2건밖에 안 떠서 사용자가
기준을 바꾸자고 제안 - "직전 봉 1개가 아니라, 최근 30개 전봉 중 가장 작았던 폭"을
기준으로 삼아서, 지금 봉 폭이 그 최솟값의 2배 이상이면 진입.

(`use_min_width_breakout=True, min_width_lookback=30, min_width_mult=2.0`)

구 state machine의 squeeze_min과 다른 점: squeeze_min은 "스퀴즈 상태에 진입한 이후로만"
갱신되는 래칫이라 죽은 횡보장이 오래가면 한없이 수축하지만, 이건 매 시점 "최근 30개
캔들"이라는 고정 크기 롤링 윈도우 최솟값이라 오래된 값이 자연히 밀려나감. 스퀴즈
선행조건도 없음(2candle_breakout과 동일한 설계 방향 유지).

방향판정은 기존과 동일(use_hma_direction_only=True, HMA200/600 정배열=롱/역배열=숏).
청산로직도 완전히 그대로 유지(0단계 HMA200 하드룰[close 체결가로 수정된 버전],
trend_follow, profit_lock 0.5%/0.85%) - 진입 타이밍만 교체하는 실험.

스코프: XRP만, 15분봉, 365일치.
"""
import sys
import os
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

SYMBOL = "XRPUSDT"
INTERVAL = "15"
DAYS = 365

bcl.SQUEEZE_ENTER_MULT = 0.7
bcl.BREAKOUT_MULT = 1.6
PLT, PLR = 0.5, 0.85
MIN_WIDTH_LOOKBACK = 30
MIN_WIDTH_MULT = 2.0

candles = bcl.fetch_klines(SYMBOL, INTERVAL, DAYS)

trades, seed_end = bcl.run_backtest(
    candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
    use_hma_direction_only=True,
    use_min_width_breakout=True, min_width_lookback=MIN_WIDTH_LOOKBACK, min_width_mult=MIN_WIDTH_MULT)

print(f"\n총 거래수: {len(trades)}건")
if not trades:
    print("거래 없음 - 종료")
    sys.exit(0)

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

print(f"\n[집계] 거래수 {len(trades)}건  승률 {win_rate:.1f}%  PF {pf:.2f}  MDD {mdd:.1f}%  평균보유 {avg_hold:.1f}h")
print(f"  거래당 평균 raw% {avg_pct:+.3f}%  비복리 단순합산% {sum_pct:+.1f}%  (복리총수익률 {total_return:+.2f}%, 참고용)")
print("  종료사유:", ", ".join(f"{k} {v}건({v/len(trades)*100:.1f}%)" for k, v in reasons.items()))

buckets = defaultdict(list)
for t in trades:
    dt = datetime.fromtimestamp(t["entry_ts"] / 1000)
    key = (dt.year, dt.month)
    buckets[key].append(t)

months = sorted(buckets.keys())

print("\n| 월 | 거래수 | 익절 | 손절 | 승률 | PF | 거래당평균% | 비복리합산% |")
print("|---|---|---|---|---|---|---|---|")

cum_sum_pct = 0.0
total_wins = 0
total_losses = 0
for (y, m) in months:
    mt = buckets[(y, m)]
    mwins = [t for t in mt if t["profit"] > 0]
    mlosses = [t for t in mt if t["profit"] <= 0]
    total_wins += len(mwins)
    total_losses += len(mlosses)
    m_win_rate = len(mwins) / len(mt) * 100
    m_gross_win = sum(t["profit"] for t in mwins)
    m_gross_loss = -sum(t["profit"] for t in mlosses)
    m_pf = m_gross_win / m_gross_loss if m_gross_loss > 0 else float("inf")
    m_avg_pct = sum(t["pct"] for t in mt) / len(mt)
    m_sum_pct = sum(t["pct"] for t in mt)
    cum_sum_pct += m_sum_pct
    pf_str = f"{m_pf:.2f}" if m_pf != float("inf") else "inf"
    print(f"| {y}-{m:02d} | {len(mt)} | {len(mwins)} | {len(mlosses)} | {m_win_rate:.1f}% | {pf_str} | {m_avg_pct:+.3f}% | {m_sum_pct:+.1f}% |")

print(f"\n합계: 익절 {total_wins}건 / 손절 {total_losses}건 (총 {total_wins+total_losses}건)")
print(f"\n누적 비복리 합산%: {cum_sum_pct:+.1f}%  (전체 {len(trades)}건 기준)")
print("\n=== MIN WIDTH BREAKOUT XRP 1Y TEST COMPLETE ===", flush=True)
