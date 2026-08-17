"""
2026-08-17: 밴드폭/캔들크기 두 트리거 실험이 전부 지금 라이브(PF 1.35)를 못 넘어서,
사용자 제안대로 아예 다른 지표인 SuperTrend(ATR 기반 표준 추세추종 지표)를 진입과
청산 양쪽에 붙여서 테스트. backtest_current_live.py에 compute_supertrend_series()
(TradingView 표준 알고리즘, period=10/multiplier=3.0 기본값) +
use_supertrend_breakout(진입: SuperTrend 방향 플립 자체를 신호+방향으로 사용)/
use_supertrend_trail(청산: pure_regime_trail과 동일 구조로 SL/TP/profit_lock/stall_exit를
전부 끄고 SuperTrend가 불리하게 뒤집히는 순간에만 청산) 신규 추가.

사전 검증(diag 스크립트): XRP 15분봉 1년 기준 period=10/mult=3.0으로 770회 플립
(평균 45.5캔들=11.4시간당 1회), close 대비 라인 괴리율 평균 1.0% - 정상 범위.

4가지 조합 비교:
  1) BASELINE: 지금 라이브 그대로(밴드폭 트리거 + 기존 청산 스택)
  2) ENTRY만 SuperTrend로 교체(청산은 기존 스택 유지)
  3) EXIT만 SuperTrend 트레일링으로 교체(진입은 기존 밴드폭 트리거 유지)
  4) 진입+청산 둘 다 SuperTrend(순수 SuperTrend 전략)

스코프: XRP만(1차 검증), 15분봉, 365일치.
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
PLT, PLR = 0.5, 0.85
STALL_CANDLES = 8
STALL_MIN_PEAK = 0.5
STALL_SL_PCT = 0.4
ST_PERIOD = 10
ST_MULT = 3.0

base_kwargs = dict(
    profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
    use_price_alignment_filter=True,
    stall_exit_candles=STALL_CANDLES, stall_exit_min_peak_pct=STALL_MIN_PEAK,
    stall_exit_sl_pct=STALL_SL_PCT,
)
live_entry_kwargs = dict(use_hma_direction_only=True, use_fast_breakout=True,
                          fast_breakout_lookback=2, fast_breakout_mult=None)

VARIANTS = [
    ("BASELINE(지금 라이브)", dict(base_kwargs, **live_entry_kwargs)),
    ("ENTRY=SuperTrend, EXIT=기존", dict(base_kwargs,
        use_supertrend_breakout=True, supertrend_period=ST_PERIOD, supertrend_multiplier=ST_MULT)),
    ("ENTRY=기존, EXIT=SuperTrend trail", dict(base_kwargs, **live_entry_kwargs,
        use_supertrend_trail=True, supertrend_period=ST_PERIOD, supertrend_multiplier=ST_MULT)),
    ("ENTRY+EXIT 둘다 SuperTrend", dict(base_kwargs,
        use_supertrend_breakout=True, use_supertrend_trail=True,
        supertrend_period=ST_PERIOD, supertrend_multiplier=ST_MULT)),
]

bcl.SQUEEZE_ENTER_MULT = 0.7
bcl.BREAKOUT_MULT = 1.6

candles = bcl.fetch_klines(SYMBOL, INTERVAL, DAYS)


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

print("\n=== SUPERTREND ENTRY/EXIT XRP 1Y TEST COMPLETE ===", flush=True)
