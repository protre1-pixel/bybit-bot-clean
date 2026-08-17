"""
2026-08-17(12차): bo=1.4(BREAKOUT_MULT 완화)를 4코인에 적용해보니 XRP만 좋아 보이고
BTC/ETH/SOL은 전부 악화(BTC는 PF<1까지 붕괴)되어 일반화되지 않음을 확인. 다만 사용자가
"sq(SQUEEZE_ENTER_MULT)를 0.8~1까지 올리면서 bo=1.4와 같이 쓰면 어떠냐"고 재요청 -
이전에 sq만 단독으로 올렸을 때(bo=1.6 고정)는 PF/MDD가 나빠졌었는데, bo=1.4와 조합하면
결과가 달라지는지 XRP로 확인.

SQUEEZE_ENTER_MULT를 0.8/0.9/1.0 3가지로, BREAKOUT_MULT는 1.4로 고정해서 조합 테스트.
라이브(sq=0.7, bo=1.6) 기준값도 같이 표기해서 비교.

exit/방향판정 스택은 라이브 그대로(profit_lock+HMA갭 트레일링, stall_exit,
use_hma_direction_only, fast_breakout), use_regime_exit=False(라이브 미반영 실험옵션이므로
비활성 유지).

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
    ("TEST(sq=0.8, bo=1.4)", (0.8, 1.4)),
    ("TEST(sq=0.9, bo=1.4)", (0.9, 1.4)),
    ("TEST(sq=1.0, bo=1.4)", (1.0, 1.4)),
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

print("\n=== SQ+BO14 XRP 1Y TEST COMPLETE ===", flush=True)
