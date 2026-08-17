"""
2026-08-17(5차): entry+exit 둘 다 SuperTrend로 바꾼 3가지 조합이 전부 베이스라인(PF 1.35)을
못 넘음을 확인(4차까지). 사용자가 재확인 질문("0.5%에서 바로 익절하는 거 아니지 않냐,
추세 타지 않냐")에 코드를 다시 읽고 정정: profit_lock_trigger_pct는 즉시청산이 아니라
peak_profit의 85%를 SL 바닥으로 래칫하는 트레일링이고, 실제로 거래의 81.4%가
"Trend Follow Stop"(HMA갭 트레일링+profit_lock 트레일링 병용)으로 종료됨 - 즉 지금
전략도 추세를 탐. SuperTrend가 진 진짜 이유는 "단타라 추세 안 타서"가 아니라 SuperTrend의
ATR 밴드 트레일링이 HMA갭 트레일링보다 훨씬 둔감(괴리율 평균 1%)해서 반납이 컸던 것.

사용자 제안(5차) - 그럼 트리거(밴드폭 스퀴즈/fast_breakout)와 청산(profit_lock+HMA갭
트레일링)은 지금 라이브 그대로 두고, "롱/숏 방향판정" 단계만 HMA200/600 정배열 부호
(use_hma_direction_only) 대신 SuperTrend 방향(supertrend_dir 부호)으로 바꿔서 딱 그
한 변수만 격리 비교. backtest_current_live.py에 use_supertrend_direction_only(신규) 추가:
breakout_now는 기존 트리거가 그대로 결정하고, 방향만 완성봉 t-1의 SuperTrend 부호로 결정
(nan=워밍업이면 진입 취소). use_price_alignment_filter 등 방향-무관 필터는 공용 "elif
signal:" 분기를 그대로 타므로 코드 추가 수정 없이 동일 적용됨.

기본 파라미터(period=10/mult=3.0) + 더 타이트한(period=7/mult=1.5, 방향 신호가 더 자주
갱신되는지) 두 세트로 민감도 비교.

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
)
trigger_kwargs = dict(use_fast_breakout=True, fast_breakout_lookback=2, fast_breakout_mult=None)

VARIANTS = [
    ("BASELINE(지금 라이브, 방향=HMA)", dict(base_kwargs, **trigger_kwargs, use_hma_direction_only=True)),
    ("방향만 SuperTrend p10/m3.0(표준)", dict(base_kwargs, **trigger_kwargs,
        use_supertrend_direction_only=True, supertrend_period=10, supertrend_multiplier=3.0)),
    ("방향만 SuperTrend p7/m1.5(타이트)", dict(base_kwargs, **trigger_kwargs,
        use_supertrend_direction_only=True, supertrend_period=7, supertrend_multiplier=1.5)),
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

print("\n=== SUPERTREND DIRECTION-ONLY XRP 1Y TEST COMPLETE ===", flush=True)
