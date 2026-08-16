"""
2026-08-16: "전략#2"(방향=HMA200/600 regime 부호, use_hma_direction_only=True)의 근본 문제로
지목된 "눌림목 진입"(진입 순간 가격이 이미 HMA200 반대쪽에 있어서, 다음 캔들 만에 0단계
HMA200 하드이탈룰에 바로 걸려 즉시청산)을 진입 단에서 원천 차단하는 필터 추가.

기존에도 `use_price_alignment_filter`(2026-08-12)가 있었지만, 그건 방향을 "캔들 몸통"으로
정하는 구경로에서만 동작했고 use_hma_direction_only=True 경로에서는 "방향 자체가 이미 HMA
regime 기준이라 불필요"로 스킵됐음. 이번에 코드 수정: use_hma_direction_only=True여도
use_price_alignment_filter=True면 추가로 아래 조건을 만족해야 진입 허용:

  롱: 가격 > HMA200 > HMA600  (완전 정배열, 가격도 눌림 없이 위)
  숏: 가격 < HMA200 < HMA600  (완전 역배열, 가격도 눌림 없이 아래)

진입 타이밍(브레이크아웃 감지)은 오늘 실험한 2candle/min_width 방식들이 전부 성과가
안 좋았으므로, 일단 기존/라이브과 동일한 스퀴즈 state machine(sq=0.7/bo=1.6)으로 되돌려서
"이 필터 하나만 추가했을 때" 효과를 격리해서 봄. 청산로직은 완전히 그대로(0단계 HMA200
하드룰[close 체결가], trend_follow, profit_lock 0.5%/0.85%).

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

candles = bcl.fetch_klines(SYMBOL, INTERVAL, DAYS)

trades, seed_end = bcl.run_backtest(
    candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
    use_hma_direction_only=True, use_price_alignment_filter=True)

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

# 복리(실제 사이징) 시뮬레이션 및 파산 시점 추적
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
print("\n=== PRICE ALIGNMENT ENTRY FILTER XRP 1Y TEST COMPLETE ===", flush=True)
