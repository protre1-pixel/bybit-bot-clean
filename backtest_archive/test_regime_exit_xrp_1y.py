"""
2026-08-17(6차): 사용자 질문 - "우리 전략 추세추종인데, 가격이 200일선(HMA200)에 닿으면
바로 청산하는 게 좀 애매하지 않냐. 200/600 정배열(큰 추세)이 살아있으면 그냥 들고가는 게
어떠냐" - normal 단계 하드청산룰(가격 vs HMA200 단일선, 인트라바 저가/고가 기준)이 너무
민감한 거 아니냐는 지적.

코드 확인 결과 이미 2026-08-14에 만들어둔 실험 옵션 use_regime_exit이 정확히 이 아이디어:
True면 "가격이 HMA200을 스치는 순간"이 아니라 "HMA200 vs HMA600 정배열 자체가 불리하게
뒤집히는 순간"(해당 캔들 종가 기준)에만 청산하도록 바뀜 - 즉 정배열/역배열(큰 추세)이
살아있는 한 가격이 HMA200 위아래로 흔들려도 계속 보유. 다만 이 옵션이 실제로 XRP에서
테스트된 기록이 없어서 baseline과 직접 비교.

trigger/exit 스택은 지금 라이브 그대로(밴드폭 스퀴즈+fast_breakout, HMA 방향판정,
profit_lock+HMA갭 트레일링, stall_exit) 유지한 채 use_regime_exit 하나만 격리 비교.

candles는 기존에 pickle로 캐시해둔 것 재사용(재조회 방지).

스코프: XRP만, 15분봉, 365일치.
"""
import sys
import os
import pickle
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

PLT, PLR = 0.5, 0.85
STALL_CANDLES = 8
STALL_MIN_PEAK = 0.5
STALL_SL_PCT = 0.4

base_kwargs = dict(
    profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
    use_price_alignment_filter=True,
    stall_exit_candles=STALL_CANDLES, stall_exit_min_peak_pct=STALL_MIN_PEAK,
    stall_exit_sl_pct=STALL_SL_PCT,
    use_hma_direction_only=True,
    use_fast_breakout=True, fast_breakout_lookback=2, fast_breakout_mult=None,
)

VARIANTS = [
    ("BASELINE(가격 vs HMA200 즉시청산)", dict(base_kwargs, use_regime_exit=False)),
    ("REGIME EXIT(200/600 정배열 뒤집힐 때만 청산)", dict(base_kwargs, use_regime_exit=True)),
]

bcl.SQUEEZE_ENTER_MULT = 0.7
bcl.BREAKOUT_MULT = 1.6

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_xrp_candles.pkl"), "rb") as f:
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

print("\n=== REGIME EXIT XRP 1Y TEST COMPLETE ===", flush=True)
