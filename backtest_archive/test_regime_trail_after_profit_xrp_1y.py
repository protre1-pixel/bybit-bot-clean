"""
2026-08-16: pure_regime_trail(진입 직후부터 정배열/역배열로만 트레일링)이 PF 0.56/MDD 100%로
대참사였던 원인 진단 - 보호장치 없는 "수익 나기 전" 구간에서 평균보유가 39.1h로 늘어지며
크게 물림. 사용자 요청으로 재검증: 수익이 나기 전까지는 지금 방식(단계0 HMA200 하드이탈,
밴드폭 SL/TP, stall_exit 등) 그대로 유지하고, peak_profit_pct가 일정 수준(수익권) 찍은
"이후부터만" 기존 트레일링(profit_lock/HMA갭수축/본전방어)을 끄고 순수 regime 뒤집힘
청산으로 전환(backtest_current_live.py의 신규 regime_trail_after_profit_pct 옵션).

수익 기준점(threshold)은 기존에 이미 쓰는 profit_lock_trigger_pct(0.5%)와 동일하게 맞춰서
"프로핏락이 걸리기 시작하는 시점 = regime 트레일링 시작 시점"으로 통일. 참고용으로 더 낮은
기준(0.2%)도 같이 비교.

스코프: XRP만, 15분봉, 365일치.
"""
import sys
import os
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

SYMBOL = "XRPUSDT"
INTERVAL = "15"
DAYS = 365

bcl.SQUEEZE_ENTER_MULT = 0.7
bcl.BREAKOUT_MULT = 1.6
PLT, PLR = 0.5, 0.85

candles = bcl.fetch_klines(SYMBOL, INTERVAL, DAYS)


def summarize(trades, seed_end, label):
    print(f"\n=== {label} ===")
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

    seed = bcl.SEED
    equity = [seed]
    ruin_idx = None
    for i, t in enumerate(trades):
        seed += t["profit"]
        equity.append(seed)
        if seed <= 0 and ruin_idx is None:
            ruin_idx = i
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

    if ruin_idx is not None:
        print(f"[!!] 복리 파산: 거래#{ruin_idx+1}/{len(trades)} 시점에 시드 <= 0")
    else:
        print(f"[OK] 복리 파산 없음. 최종시드=${seed_end:.2f}")

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


common_kwargs = dict(
    profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
    use_hma_direction_only=True, use_price_alignment_filter=True,
    use_fast_breakout=True, fast_breakout_lookback=2, fast_breakout_mult=None,
)

trades_live, seed_live = bcl.run_backtest(candles, **common_kwargs)
summarize(trades_live, seed_live, "1) 현재 라이브 그대로 (기준선)")

trades_pure, seed_pure = bcl.run_backtest(candles, **common_kwargs, pure_regime_trail=True)
summarize(trades_pure, seed_pure, "2) 진입 직후부터 regime만 트레일링 (지난 테스트, 참고용)")

trades_after05, seed_after05 = bcl.run_backtest(candles, **common_kwargs, regime_trail_after_profit_pct=0.5)
summarize(trades_after05, seed_after05,
          "3) 수익 0.5%(profit_lock 트리거) 찍기 전까지는 기존방식, 그 이후부터만 regime 트레일링")

trades_after02, seed_after02 = bcl.run_backtest(candles, **common_kwargs, regime_trail_after_profit_pct=0.2)
summarize(trades_after02, seed_after02,
          "4) 수익 0.2% 찍기 전까지는 기존방식, 그 이후부터만 regime 트레일링 (더 이른 전환)")

print("\n=== REGIME TRAIL AFTER PROFIT XRP 1Y TEST COMPLETE ===", flush=True)
