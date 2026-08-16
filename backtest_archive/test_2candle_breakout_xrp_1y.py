"""
2026-08-16: 사용자 제안 - 기존 스퀴즈 선행조건부 state machine(normal→squeeze→breakout)을
완전히 버리고, "딱 2개 완성봉만 비교"하는 방식으로 교체.

방식: 매 완성된 캔들 t마다, t시점 폭(width_info_at(candles, t))이 직전 완성봉 t-1시점 폭
(width_info_at(candles, t-1))의 2.5배 이상이면 스퀴즈 여부와 무관하게 즉시 breakout으로
인정하고 롱/숏 진입 (`use_2candle_breakout=True, two_candle_breakout_mult=2.5`).

사용자가 확정한 4가지:
  1) 위 방식대로 (스퀴즈 선행조건 없이 2봉 비교, 2.5배)
  2) 폭 기준은 볼린저밴드 폭(width_info_at, 기존 라이브 계산방식 그대로 재사용)
  3) 15분봉
  4) 방향판정은 기존과 동일 (HMA200/600 정배열=롱, 역배열=숏 - use_hma_direction_only=True)

청산로직은 이번엔 의도적으로 완전히 그대로 유지(0단계 HMA200 하드룰[버그 수정된 close 체결가],
1단계 trend_follow, profit_lock 0.5%/0.85%) - 진입 타이밍 하나만 바꿨을 때 효과를 격리해서
보기 위함. 청산 로직 자체의 문제(진입 직후 15분만에 HMA200 이탈로 즉시 청산되는 문제)는
사용자도 동일하게 남을 것으로 예상 중이며, 이번 결과 확인 후 별도로 다룰 예정.

스코프: XRP만, 15분봉, 365일치, sq/bo(구 state machine 파라미터, 이번엔 안 씀 - 라이브 값
0.7/1.6 유지만 해둠), profit_lock(0.5/0.85) 유지.
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
TWO_CANDLE_MULT = 2.5

candles = bcl.fetch_klines(SYMBOL, INTERVAL, DAYS)

trades, seed_end = bcl.run_backtest(
    candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
    use_hma_direction_only=True,
    use_2candle_breakout=True, two_candle_breakout_mult=TWO_CANDLE_MULT)

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
print("\n=== 2CANDLE BREAKOUT XRP 1Y TEST COMPLETE ===", flush=True)
