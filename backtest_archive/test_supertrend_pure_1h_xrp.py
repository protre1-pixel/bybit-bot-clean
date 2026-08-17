"""
2026-08-17(4차): 15분봉 단타봇 구조(profit_lock 0.5%/stall_exit 8캔들)에 SuperTrend를
끼워넣으면 파라미터를 아무리 조여도 베이스라인을 못 넘는다는 걸 확인(3차 스크립트).
사용자가 "그럼 수퍼트렌드로는 매매가 아예 안되는거냐"고 재질문 - 이건 별개의 질문:
"이 15분봉 단타봇 구조와 안 맞는다" vs "SuperTrend 자체가 매매에 못 쓰는 지표다"를
분리해서 확인해야 함.

SuperTrend는 원래 긴 타임프레임(1h~1D) + 추세를 끝까지 태우는 순수 추세추종 스타일과
궁합이 좋은 지표. 그래서 다른 로직(profit_lock/stall_exit/필터) 없이 순수
ENTRY=SuperTrend breakout / EXIT=SuperTrend flip 조합만으로, 훨씬 긴 타임프레임(1시간봉,
2년치)에서 XRP 자체적으로 수익이 나는지를 따로 검증. use_supertrend_trail이 켜지면
use_pure_trail_now 분기로 profit_lock/stall_exit가 전부 자동 바이패스되므로 코드 변경
없이 그대로 재사용 가능.

기본값(10/3.0) + 조금 더 타이트한(7/2.0) 두 가지 파라미터로 비교.

스코프: XRP만, 1시간봉, 730일치(2년), 순수 SuperTrend만(다른 필터/스택 전부 미사용).
"""
import sys
import os
import pickle
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

VARIANTS = [
    ("PURE ST 1h p10/m3.0(표준)", dict(
        use_supertrend_breakout=True, use_supertrend_trail=True,
        supertrend_period=10, supertrend_multiplier=3.0)),
    ("PURE ST 1h p7/m2.0", dict(
        use_supertrend_breakout=True, use_supertrend_trail=True,
        supertrend_period=7, supertrend_multiplier=2.0)),
]

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_xrp_1h_candles.pkl"), "rb") as f:
    candles = pickle.load(f)


def run_variant(label, kwargs):
    trades, seed_end = bcl.run_backtest(candles, **kwargs)

    print(f"\n{'='*60}\n[{label}]\n{'='*60}")
    print(f"총 거래수: {len(trades)}건")
    if not trades:
        print("거래 없음")
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

    print(f"[집계] 거래수 {len(trades)}건  승률 {win_rate:.1f}%  PF {pf:.2f}  MDD {mdd:.1f}%  평균보유 {avg_hold:.1f}h")
    print(f"  거래당 평균 raw% {avg_pct:+.3f}%  비복리 단순합산% {sum_pct:+.1f}%  (복리총수익률 {total_return:+.2f}%, 참고용)")
    print("  종료사유:", ", ".join(f"{k} {v}건({v/len(trades)*100:.1f}%)" for k, v in reasons.items()))

    buckets = defaultdict(list)
    for t in trades:
        dt = datetime.fromtimestamp(t["entry_ts"] / 1000)
        buckets[(dt.year, dt.month)].append(t)
    months = sorted(buckets.keys())

    print("\n| 월 | 거래수 | 익절 | 손절 | 승률 | PF | 거래당평균% | 비복리합산% |")
    print("|---|---|---|---|---|---|---|---|")
    cum_sum_pct = 0.0
    for (y, m) in months:
        mt = buckets[(y, m)]
        mwins = [t for t in mt if t["profit"] > 0]
        mlosses = [t for t in mt if t["profit"] <= 0]
        m_win_rate = len(mwins) / len(mt) * 100
        m_gross_win = sum(t["profit"] for t in mwins)
        m_gross_loss = -sum(t["profit"] for t in mlosses)
        m_pf = m_gross_win / m_gross_loss if m_gross_loss > 0 else float("inf")
        m_avg_pct = sum(t["pct"] for t in mt) / len(mt)
        m_sum_pct = sum(t["pct"] for t in mt)
        cum_sum_pct += m_sum_pct
        pf_str = f"{m_pf:.2f}" if m_pf != float("inf") else "inf"
        print(f"| {y}-{m:02d} | {len(mt)} | {len(mwins)} | {len(mlosses)} | {m_win_rate:.1f}% | {pf_str} | {m_avg_pct:+.3f}% | {m_sum_pct:+.1f}% |")
    print(f"\n누적 비복리 합산%: {cum_sum_pct:+.1f}%")


for label, kwargs in VARIANTS:
    run_variant(label, kwargs)

print("\n=== SUPERTREND PURE 1H XRP TEST COMPLETE ===", flush=True)
