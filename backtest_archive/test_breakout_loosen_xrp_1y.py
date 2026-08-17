"""
2026-08-17(10차): 직전 테스트(test_squeeze_loosen_xrp_1y.py)에서 SQUEEZE_ENTER_MULT를
올려 진입을 완화하면 거래수는 늘지만 PF/MDD가 나빠짐을 확인. 이번엔 BREAKOUT_MULT를
격리해서 완화 방향(라이브 1.6 대비 낮은 값 = "덜 확장해도 브레이크아웃 인정" = 더 민감)
으로 테스트. 사용자 요청: bo를 1.3부터 각각 테스트.

BREAKOUT_MULT는 "과거 폭 대비 지금 폭이 이 배수 넘게 확장하면 브레이크아웃 발동" 조건이라
값을 낮추면(1.6→1.3) 더 적은 확장에도 발동 - SQUEEZE_ENTER_MULT와 달리 낮추는 쪽이
완화(민감화) 방향. SQUEEZE_ENTER_MULT는 라이브 값(0.7) 그대로 고정한 채 BREAKOUT_MULT만
1.3/1.4/1.5/1.6(라이브) 4가지로 비교.

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
    ("TEST(sq=0.7, bo=1.3)", (0.7, 1.3)),
    ("TEST(sq=0.7, bo=1.4)", (0.7, 1.4)),
    ("TEST(sq=0.7, bo=1.5)", (0.7, 1.5)),
    ("LIVE(sq=0.7, bo=1.6)", (0.7, 1.6)),
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

print("\n=== BREAKOUT LOOSEN XRP 1Y TEST COMPLETE ===", flush=True)
