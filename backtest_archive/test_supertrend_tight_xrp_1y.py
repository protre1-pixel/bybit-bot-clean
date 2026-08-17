"""
2026-08-17(3차): SuperTrend 진입/청산 4조합 테스트에서 전부 베이스라인(PF 1.35)을
못 넘긴 것에 대해 사용자가 "SuperTrend가 진짜 그렇게 도움이 안 되냐"고 재질문.

가설: period=10/mult=3.0은 TradingView 표준 기본값이지만 원래 일봉/4시간봉 스윙트레이딩용
튜닝값. 사전 검증에서 이 설정의 close-vs-line 괴리율이 평균 1.036%인데, 지금 라이브
전략은 profit_lock_trigger_pct=0.5%(0.5% 수익나면 바로 85% 잠금 시작)이고 거래당 평균
raw%가 +0.242%에 불과함 - 즉 SuperTrend가 "뒤집힐 때까지" 기다리는 폭이 이 전략이
실제로 먹는 이익 폭보다 3~4배 넓어서, 뒤집히기 전에 이미 이익 대부분 반납.

이게 진짜 원인(파라미터 미스매치)인지, 아니면 지표 자체가 이 전략 구조에 근본적으로
안 맞는 것인지 구분하기 위해 훨씬 타이트한 multiplier(1.0~2.0)로 재테스트.
EXIT=SuperTrend trail 단독(3번 조합, 가장 나빴던 조합: PF 0.62, MDD 96.7%)과
ENTRY+EXIT 풀 SuperTrend(4번 조합: PF 0.89) 두 가지 구조에 대해 mult를 좁혀가며 비교.

candles는 이전 실행에서 pickle로 캐시해둔 것 재사용(재조회 방지).

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
live_entry_kwargs = dict(use_hma_direction_only=True, use_fast_breakout=True,
                          fast_breakout_lookback=2, fast_breakout_mult=None)

VARIANTS = [
    ("EXIT=ST trail p10/m3.0(기존)", dict(base_kwargs, **live_entry_kwargs,
        use_supertrend_trail=True, supertrend_period=10, supertrend_multiplier=3.0)),
    ("EXIT=ST trail p10/m2.0", dict(base_kwargs, **live_entry_kwargs,
        use_supertrend_trail=True, supertrend_period=10, supertrend_multiplier=2.0)),
    ("EXIT=ST trail p10/m1.5", dict(base_kwargs, **live_entry_kwargs,
        use_supertrend_trail=True, supertrend_period=10, supertrend_multiplier=1.5)),
    ("EXIT=ST trail p7/m1.0", dict(base_kwargs, **live_entry_kwargs,
        use_supertrend_trail=True, supertrend_period=7, supertrend_multiplier=1.0)),
    ("FULL ST p10/m3.0(기존)", dict(base_kwargs,
        use_supertrend_breakout=True, use_supertrend_trail=True,
        supertrend_period=10, supertrend_multiplier=3.0)),
    ("FULL ST p10/m1.5", dict(base_kwargs,
        use_supertrend_breakout=True, use_supertrend_trail=True,
        supertrend_period=10, supertrend_multiplier=1.5)),
    ("FULL ST p7/m1.0", dict(base_kwargs,
        use_supertrend_breakout=True, use_supertrend_trail=True,
        supertrend_period=7, supertrend_multiplier=1.0)),
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


for label, kwargs in VARIANTS:
    run_variant(label, kwargs)

print("\n=== SUPERTREND TIGHT MULT XRP 1Y TEST COMPLETE ===", flush=True)
