"""
2026-08-16: fast_breakout-only가 XRP에서만 반짝(PF2.18)이고 BTC/SOL은 PF<1(손실)로 나온 뒤,
"스퀴즈 SM(sq=0.7/bo=1.6) + fast_breakout 혼합"(XRP 228건, PF1.10->1.13, MDD59.2->61.5,
복리$1625->$2889) 버전을 다른 코인에도 검증. fast_breakout-only보다 보수적인(스퀴즈 래칫이
주경로, fast_breakout은 보조) 조합이 심볼 간 일반화가 더 나은지 확인.

설정: SQUEEZE_ENTER_MULT=0.7(정상), BREAKOUT_MULT=1.6, use_fast_breakout=True(lookback=2,
mult=BREAKOUT_MULT 재사용), use_hma_direction_only + use_price_alignment_filter,
profit_lock 0.5%/0.85%. 15분봉, 365일치.

대상: BTCUSDT, ETHUSDT, SOLUSDT
"""
import sys
import os
from datetime import datetime
from collections import defaultdict

SYMBOLS = [s.upper() for s in sys.argv[1:]] if len(sys.argv) > 1 else ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_orig_argv = sys.argv
sys.argv = [_orig_argv[0]]
import backtest_current_live as bcl
sys.argv = _orig_argv

INTERVAL = "15"
DAYS = 365
PLT, PLR = 0.5, 0.85


def run_one(symbol):
    bcl.SQUEEZE_ENTER_MULT = 0.7
    bcl.BREAKOUT_MULT = 1.6

    candles = bcl.fetch_klines(symbol, INTERVAL, DAYS)
    trades, seed_end = bcl.run_backtest(
        candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
        use_hma_direction_only=True, use_price_alignment_filter=True,
        use_fast_breakout=True, fast_breakout_lookback=2, fast_breakout_mult=None)

    print(f"\n{'='*60}\n[{symbol}]\n{'='*60}")
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
    ruin_ts = None
    for i, t in enumerate(trades):
        seed += t["profit"]
        equity.append(seed)
        if seed <= 0 and ruin_idx is None:
            ruin_idx = i
            ruin_ts = t["exit_ts"]
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
        dt = datetime.fromtimestamp(ruin_ts/1000)
        print(f"[!!] 복리 파산: 거래#{ruin_idx+1}/{len(trades)}, {dt} 시점에 시드 <= 0")
    else:
        print(f"[OK] 복리 파산 없음. 최종시드=${seed_end:.2f}")

    buckets = defaultdict(list)
    for t in trades:
        dt = datetime.fromtimestamp(t["entry_ts"] / 1000)
        key = (dt.year, dt.month)
        buckets[key].append(t)
    months = sorted(buckets.keys())

    print("\n| 월 | 거래수 | 익절 | 손절 | 승률 | PF | 거래당평균% | 비복리합산% |")
    print("|---|---|---|---|---|---|---|---|")
    cum_sum_pct = 0.0
    total_wins = 0
    total_losses = 0
    for (y, m) in months:
        mt = buckets[(y, m)]
        mwins = [t for t in mt if t["profit"] > 0]
        mlosses = [t for t in mt if t["profit"] <= 0]
        total_wins += len(mwins)
        total_losses += len(mlosses)
        m_win_rate = len(mwins) / len(mt) * 100
        m_gross_win = sum(t["profit"] for t in mwins)
        m_gross_loss = -sum(t["profit"] for t in mlosses)
        m_pf = m_gross_win / m_gross_loss if m_gross_loss > 0 else float("inf")
        m_avg_pct = sum(t["pct"] for t in mt) / len(mt)
        m_sum_pct = sum(t["pct"] for t in mt)
        cum_sum_pct += m_sum_pct
        pf_str = f"{m_pf:.2f}" if m_pf != float("inf") else "inf"
        print(f"| {y}-{m:02d} | {len(mt)} | {len(mwins)} | {len(mlosses)} | {m_win_rate:.1f}% | {pf_str} | {m_avg_pct:+.3f}% | {m_sum_pct:+.1f}% |")

    print(f"\n합계: 익절 {total_wins}건 / 손절 {total_losses}건 (총 {total_wins+total_losses}건)")
    print(f"누적 비복리 합산%: {cum_sum_pct:+.1f}%  (전체 {len(trades)}건 기준)")


for sym in SYMBOLS:
    run_one(sym)

print("\n=== FAST BREAKOUT MIXED MULTI-SYMBOL TEST COMPLETE ===", flush=True)
