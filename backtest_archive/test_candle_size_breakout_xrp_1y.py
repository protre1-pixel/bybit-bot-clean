"""
2026-08-17: 사용자 제안 - "지금은 밴드폭을 트리거로 잡는데, 이걸 캔들 크기로 잡아보자.
방식은 비슷한데(밴드폭 기반 대안 옵션 2개-2candle_breakout/min_width_breakout-가 이미
있듯) 캔들이 평균 크기 이상으로 커지면 신호 발생하는 거지?" 라는 요청에 따라
backtest_current_live.py에 use_candle_size_breakout(신규, 2026-08-17)을 추가함:
매 완성봉의 크기(high-low)가 직전 candle_size_lookback개 완성봉 크기 평균의
candle_size_mult배(None이면 BREAKOUT_MULT 재사용) 이상이면 스퀴즈 선행조건 없이 즉시
breakout 인정. min_width_breakout과 구조는 동일(롤링 윈도우 대비 배율)하나 기준이
"밴드폭(종가 SMA±2std)"이 아니라 "캔들 자체 고가-저가 범위"라는 점이 다름.

베이스라인은 "지금 우리 라이브 전략"(현재 배포된 완전체: SQUEEZE_ENTER_MULT=0.7,
BREAKOUT_MULT=1.6, use_hma_direction_only, use_price_alignment_filter, use_fast_breakout,
profit_lock 0.5%/0.85%, stall_exit 8캔들/0.5%/0.4%) 그대로. 캔들크기 트리거 변형들은
진입 트리거만 candle_size_breakout으로 교체하고(스퀴즈/fast_breakout 로직은 우선순위상
자동 비활성) 나머지(방향판정/필터/청산/profit_lock/stall_exit)는 전부 동일하게 유지해서
"진입 타이밍 소스"만 순수 비교.

스코프: XRP만(1차 검증), 15분봉, 365일치. lookback/mult 조합 3종 비교.
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

base_kwargs = dict(
    profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
    use_hma_direction_only=True, use_price_alignment_filter=True,
    stall_exit_candles=STALL_CANDLES, stall_exit_min_peak_pct=STALL_MIN_PEAK,
    stall_exit_sl_pct=STALL_SL_PCT,
)

VARIANTS = [
    ("BASELINE(밴드폭, 지금 라이브)", dict(base_kwargs, use_fast_breakout=True, fast_breakout_lookback=2, fast_breakout_mult=None)),
    ("CANDLE_SIZE lookback=30 mult=None(=1.6)", dict(base_kwargs, use_candle_size_breakout=True, candle_size_lookback=30, candle_size_mult=None)),
    ("CANDLE_SIZE lookback=30 mult=2.0", dict(base_kwargs, use_candle_size_breakout=True, candle_size_lookback=30, candle_size_mult=2.0)),
    ("CANDLE_SIZE lookback=14 mult=2.0", dict(base_kwargs, use_candle_size_breakout=True, candle_size_lookback=14, candle_size_mult=2.0)),
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

print("\n=== CANDLE SIZE BREAKOUT XRP 1Y TEST COMPLETE ===", flush=True)
