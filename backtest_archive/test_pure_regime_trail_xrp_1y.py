"""
2026-08-16: 사용자 요청 - "진입신호 뜨고 정배/역배로 진입할 때, 진입 후엔 아무것도 보지말고
200/600 정배열/역배열로만 트레일링하면 어떻게 되는지" 검증.

즉 진입은 지금 라이브 그대로(sq=0.7/bo=1.6 + fast_breakout + hma_direction_only +
price_alignment_filter)이지만, 진입 이후에는 SL/TP/profit_lock/stall_exit/단계전환
(normal→trend_follow)/HMA갭 트레일링을 전부 끄고 오직 "HMA200 vs HMA600 정배열이
포지션 방향에 불리하게 뒤집히는 순간"에만 청산(backtest_current_live.py의 신규
pure_regime_trail=True 옵션). 초기 보호 SL조차 없는 순수 regime-only 홀드 테스트.

스코프: XRP만, 15분봉, 365일치. 비교를 위해 기존(라이브 그대로) 결과도 같이 출력.
"""
import sys
import os
from collections import defaultdict

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
        from datetime import datetime
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
summarize(trades_live, seed_live, "현재 라이브 그대로 (SL/TP/profit_lock 등 전부 적용)")

trades_regime, seed_regime = bcl.run_backtest(candles, **common_kwargs, pure_regime_trail=True)
summarize(trades_regime, seed_regime, "진입은 동일 + 진입후엔 오직 HMA200/600 정배열-역배열 뒤집힐때만 청산 (그외 전부 무시)")

print("\n=== PURE REGIME TRAIL XRP 1Y TEST COMPLETE ===", flush=True)
