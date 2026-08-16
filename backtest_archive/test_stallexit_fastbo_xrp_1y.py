"""
2026-08-16: giveback 진단 결과, 지금 베스트 조합(228건)의 손실 대부분(-$8,136.61, 비복리
기준)이 peak_pct < 0.5%(profit_lock 트리거도 못 찍음)인 67건에서 나온다는 게 확인됨.
반면 peak 0.5% 이상 찍은 거래들은 이미 반납이 거의 없어서(2%+ 그룹도 평균 0.87%p만
반납) trend_follow 트레일링을 더 조이는 건 오히려 잘 달리는 추세만 건드릴 위험이 큼.

그래서 "이미 있는" stall_exit_candles 옵션으로, peak가 오래(진입 후 stall_exit_candles
캔들 이상) 지나도록 profit_lock 트리거(0.5%)도 못 찍은 거래만 선택적으로 SL을 좁힘.
잘 달리는 거래(0.5%+ 그룹)는 이 조건에 걸리기 전에 이미 peak가 올라가 있으므로 전혀
영향 안 받음 - 세션 초반 "1+2+3 콤보" 테스트와 달리 이번엔 stall 조건을 profit_lock
트리거(0.5%)에 정확히 맞춰서 "지켜야 할 다른 로직과 안 겹치게" 설계.

설정: 진입 후 8캔들(15분봉 기준 2시간) 지나도록 peak<0.5%면 SL을 진입가∓0.4%로 조임
(기존 SL이 더 타이트하면 그대로 유지, 완화는 안 함). 나머지(sq=0.7/bo=1.6, fast_breakout,
hma_direction_only, price_alignment_filter, profit_lock 0.5%/0.85%)는 전부 동일.

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

STALL_CANDLES = 8       # 2시간(15분봉 x 8)
STALL_MIN_PEAK = 0.5    # profit_lock 트리거와 동일 기준
STALL_SL_PCT = 0.4      # 진입가 대비 0.4%로 조임

candles = bcl.fetch_klines(SYMBOL, INTERVAL, DAYS)

trades, seed_end = bcl.run_backtest(
    candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
    use_hma_direction_only=True, use_price_alignment_filter=True,
    use_fast_breakout=True, fast_breakout_lookback=2, fast_breakout_mult=None,
    stall_exit_candles=STALL_CANDLES, stall_exit_min_peak_pct=STALL_MIN_PEAK,
    stall_exit_sl_pct=STALL_SL_PCT)

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

# peak<0.5% 그룹 별도 진단 (개선 여부 직접 확인)
low_peak = [t for t in trades if t["peak_pct"] < STALL_MIN_PEAK]
print(f"\n[peak<{STALL_MIN_PEAK}% 그룹] {len(low_peak)}건, profit 합계 ${sum(t['profit'] for t in low_peak):+.2f}")

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
print("\n=== STALL EXIT + FAST BREAKOUT XRP 1Y TEST COMPLETE ===", flush=True)
