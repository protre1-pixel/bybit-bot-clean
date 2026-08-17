"""
2026-08-17(13차): 진입 완화 방향(sq/bo 조정) 시도가 전부 위험조정 관점에서 역효과였음을
확인 후 이 방향은 접고, 사용자가 새 아이디어 제시 - "지금 추세(200/600 정배열)가 유지되면
가격이 200일선 닿아도 버티는(use_regime_exit) 게 있는데, 근데 지금 진입은 롱일 때
가격>200>600(완전 정배열)일 때만 들어가고 숏은 반대. 저렇게 버텨주는 로직이 있으면
200/600이 정배면 롱, 역배면 숏으로 가격이 어디 있든 그냥 진입하고 쭉 가면 어떠냐."

코드 확인 결과 이 "가격>200>600 완전정배열이어야만 진입"이 use_price_alignment_filter=True
(2026-08-12 도입) 정확히 이 필터. 원래 도입 이유는 "가격이 이미 HMA200 반대쪽에 있는(눌림목)
상태로 진입하면 0단계 하드청산룰(가격 vs HMA200)에 진입 직후 바로 걸려서 즉시손절되는 문제"를
막기 위함이었음(주석 확인). 그런데 use_regime_exit=True를 쓰면 0단계 하드청산 기준 자체가
"가격 vs HMA200"에서 "200/600 정배열 자체가 뒤집히는 순간"으로 바뀌므로, 애초에
use_price_alignment_filter가 막으려던 "눌림목 진입 직후 즉시손절" 문제가 청산 쪽에서 이미
해소됨 - 즉 진입 쪽 필터(use_price_alignment_filter)를 굳이 켜둘 이유가 없어질 수 있음.

이 가설을 검증하기 위해 4가지 조합 비교:
  A) LIVE: use_price_alignment_filter=True,  use_regime_exit=False (현재 라이브)
  B) REGIME_EXIT only: use_price_alignment_filter=True,  use_regime_exit=True (지난번 검증한 개선)
  C) NO_ALIGN only: use_price_alignment_filter=False, use_regime_exit=False (필터만 제거, 위험 - 원래
     문제 재현 예상되는 대조군)
  D) NO_ALIGN+REGIME_EXIT: use_price_alignment_filter=False, use_regime_exit=True (사용자가 원하는
     조합 - 방향은 200/600 정배열 부호로만 정하고 가격 위치 무관하게 진입, 대신 청산은 정배열
     유지되는 한 버팀)

방향판정(use_hma_direction_only=True)과 나머지 exit/trigger 스택(profit_lock+HMA갭 트레일링,
stall_exit, fast_breakout)은 4개 조합 전부 동일 유지. squeeze/breakout mult는 지난 세션
결론대로 라이브 기본값(sq=0.7, bo=1.6) 고정 - 진입완화 방향은 이미 기각됨.

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
    stall_exit_candles=STALL_CANDLES, stall_exit_min_peak_pct=STALL_MIN_PEAK,
    stall_exit_sl_pct=STALL_SL_PCT,
    use_hma_direction_only=True,
    use_fast_breakout=True, fast_breakout_lookback=2, fast_breakout_mult=None,
)

VARIANTS = [
    ("A) LIVE(align=True, regime_exit=False)", dict(base_kwargs, use_price_alignment_filter=True, use_regime_exit=False)),
    ("B) REGIME_EXIT(align=True, regime_exit=True)", dict(base_kwargs, use_price_alignment_filter=True, use_regime_exit=True)),
    ("C) NO_ALIGN(align=False, regime_exit=False)", dict(base_kwargs, use_price_alignment_filter=False, use_regime_exit=False)),
    ("D) NO_ALIGN+REGIME_EXIT(align=False, regime_exit=True)", dict(base_kwargs, use_price_alignment_filter=False, use_regime_exit=True)),
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

print("\n=== NO PRICE ALIGN + REGIME EXIT XRP 1Y TEST COMPLETE ===", flush=True)
