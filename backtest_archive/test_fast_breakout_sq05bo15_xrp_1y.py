"""
2026-08-16: 앞서 "1시간봉이냐 15분봉이냐" 혼선이 있었으나, 사용자가 15분봉으로만 진행한다고
확정. 방금 검증한 최고 조합(sq=0.7/bo=1.6 + fast_breakout + use_hma_direction_only +
use_price_alignment_filter, 228건/PF1.13/MDD61.5%/복리+188.91%)에서 SQUEEZE_ENTER_MULT/
BREAKOUT_MULT만 원래 코드 기본값인 sq=0.5/bo=1.5로 되돌려서 재검증. 나머지 조건(15분봉,
365일치, profit_lock 0.5%/0.85%, use_fast_breakout lookback=2/mult=BREAKOUT_MULT 재사용)은
전부 동일하게 유지.

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

bcl.SQUEEZE_ENTER_MULT = 0.5
bcl.BREAKOUT_MULT = 1.5
PLT, PLR = 0.5, 0.85

candles = bcl.fetch_klines(SYMBOL, INTERVAL, DAYS)

trades, seed_end = bcl.run_backtest(
    candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
    use_hma_direction_only=True, use_price_alignment_filter=True,
    use_fast_breakout=True, fast_breakout_lookback=2, fast_breakout_mult=None)

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

seed = bcl.SEED
equity = [seed]
ruin_idx = None
ruin_ts = None
for i, t in enumerate(trades):
    seed += t["profit"]
    equity.append(seed)
    if seed <= 0 and ruin_idx is None:
        ruin_idx = i
        ruin_ts = t["exit_ts"]
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

if ruin_idx is not None:
    dt = datetime.fromtimestamp(ruin_ts/1000)
    print(f"\n[!!] 복리 파산: 거래#{ruin_idx+1}/{len(trades)}, {dt} 시점에 시드 <= 0")
else:
    print(f"\n[OK] 복리 파산 없음. 최종시드=${seed_end:.2f}")

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
print("\n=== FAST BREAKOUT SQ0.5/BO1.5 XRP 1Y TEST COMPLETE ===", flush=True)
