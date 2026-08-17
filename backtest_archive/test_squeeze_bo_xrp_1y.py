"""
2026-08-17(8차): 사용자 지적 - "지금 서버에서 돌아가는거 보면 진입이 너무 느린거 같기도 한데
sq 0.5 bo 1.5로 xrp만 테스트 해볼래? 지금 이 전략대로" - 진입 트리거(밴드폭 스퀴즈/브레이크아웃)
민감도가 너무 낮아서(SQUEEZE_ENTER_MULT=0.7, BREAKOUT_MULT=1.6) 기회를 놓치는 게 아니냐는 질문.

실제 라이브(trading_service.py)의 현재 값은 SQUEEZE_ENTER_MULT=0.7, BREAKOUT_MULT=1.6 확인.
(참고: backtest_current_live.py 모듈 상단 기본값은 0.5/1.5인데, 이번 세션 다른 테스트들은
전부 실행 시점에 0.7/1.6으로 덮어써서 라이브값에 맞춰 왔음 - 이번엔 사용자가 요청한 0.5/1.5를
"지금 이 전략대로"(청산/방향판정 등 나머지 스택은 라이브 그대로, use_regime_exit=False)에
그대로 적용해서 현재 라이브(0.7/1.6) 대비 더 민감한 진입이 어떤 영향을 주는지 비교.

trigger 민감도만 격리 비교 - exit/방향판정 스택(profit_lock+HMA갭 트레일링, stall_exit,
use_hma_direction_only, fast_breakout)은 그대로 유지, use_regime_exit은 아직 라이브 미반영
실험 옵션이므로 False(현재 라이브 그대로) 유지.

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
    use_regime_exit=False,
)

VARIANTS = [
    ("LIVE(sq=0.7, bo=1.6)", (0.7, 1.6)),
    ("TEST(sq=0.5, bo=1.5)", (0.5, 1.5)),
]

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_xrp_candles.pkl"), "rb") as f:
    candles = pickle.load(f)


def run_variant(label, sq_mult, bo_mult):
    bcl.SQUEEZE_ENTER_MULT = sq_mult
    bcl.BREAKOUT_MULT = bo_mult
    trades, seed_end = bcl.run_backtest(candles, **base_kwargs)

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


for label, (sq, bo) in VARIANTS:
    run_variant(label, sq, bo)

print("\n=== SQUEEZE/BREAKOUT MULT XRP 1Y TEST COMPLETE ===", flush=True)
