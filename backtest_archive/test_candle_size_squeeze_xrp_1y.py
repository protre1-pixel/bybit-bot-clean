"""
2026-08-17(2차): test_candle_size_breakout_xrp_1y.py에서 "평균 대비 배율" 단순 방식이
스퀴즈 선행조건 없이 캔들 16개 중 1개꼴로 트리거돼서(변동성 클러스터 노이즈) PF가
1.35→0.95로 나빠진 걸 확인. 사용자 제안(2번 옵션): 밴드폭과 동일하게 "먼저 조용해졌다가
(수축) 그 다음 확장되는" 2단계 스퀴즈→브레이크아웃 구조를 캔들크기 버전에도 적용.

backtest_current_live.py에 candle_size_require_squeeze=True(신규) 추가: 전용 상태변수
cs_squeeze_status/cs_squeeze_size로 밴드폭 squeeze_status와 동일한 state machine을
캔들크기(high-low) 기준으로 복제. normal 상태에서 캔들크기가 candle_size_squeeze_mult
(0.7)배 미만으로 수축하면 squeeze 진입, squeeze 상태에서 최솟값을 계속 갱신하다가
candle_size_mult(=BREAKOUT_MULT 재사용 옵션 포함)배 이상 확장되면 breakout 인정.

베이스라인/나머지 설정은 이전 스크립트와 동일(현재 라이브 완전체 조합, 진입 트리거만 교체).

스코프: XRP만, 15분봉, 365일치. squeeze_mult/breakout_mult 조합 비교.
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
    ("CANDLE_SIZE_SQUEEZE lb=30 sq=0.7 bo=None(=1.6)", dict(base_kwargs, use_candle_size_breakout=True, candle_size_lookback=30,
        candle_size_require_squeeze=True, candle_size_squeeze_mult=0.7, candle_size_mult=None)),
    ("CANDLE_SIZE_SQUEEZE lb=30 sq=0.7 bo=2.0", dict(base_kwargs, use_candle_size_breakout=True, candle_size_lookback=30,
        candle_size_require_squeeze=True, candle_size_squeeze_mult=0.7, candle_size_mult=2.0)),
    ("CANDLE_SIZE_SQUEEZE lb=30 sq=0.5 bo=1.6", dict(base_kwargs, use_candle_size_breakout=True, candle_size_lookback=30,
        candle_size_require_squeeze=True, candle_size_squeeze_mult=0.5, candle_size_mult=1.6)),
    ("CANDLE_SIZE_SQUEEZE lb=14 sq=0.7 bo=1.6", dict(base_kwargs, use_candle_size_breakout=True, candle_size_lookback=14,
        candle_size_require_squeeze=True, candle_size_squeeze_mult=0.7, candle_size_mult=1.6)),
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

print("\n=== CANDLE SIZE SQUEEZE BREAKOUT XRP 1Y TEST COMPLETE ===", flush=True)
