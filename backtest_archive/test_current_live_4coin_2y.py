"""
2026-08-17: test_current_live_4coin_1y.py의 2년치 버전. 1년치 결과(BTC+38.7%/ETH+51.4%/
XRP+56.0%/SOL+50.9%, PF 1.10~1.35, 비복리 합산 기준)가 표본기간이 짧아 특정 구간 편향인지
확인하기 위해 동일 설정으로 기간만 730일(2년)로 늘려서 재검증.

설정(trading_service.py 라이브와 동일): SQUEEZE_ENTER_MULT=0.7, BREAKOUT_MULT=1.6,
use_hma_direction_only=True, use_price_alignment_filter=True,
use_fast_breakout=True(lookback=2, mult=BREAKOUT_MULT 재사용),
profit_lock_trigger_pct=0.5%/ratio=0.85, stall_exit_candles=8(2시간)/min_peak=0.5%/sl=0.4%.

스코프: BTCUSDT, ETHUSDT, XRPUSDT, SOLUSDT. 15분봉, 730일치(2년).
"""
import sys
import os
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT"]
INTERVAL = "15"
DAYS = 730
PLT, PLR = 0.5, 0.85
STALL_CANDLES = 8
STALL_MIN_PEAK = 0.5
STALL_SL_PCT = 0.4

common_kwargs = dict(
    profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
    use_hma_direction_only=True, use_price_alignment_filter=True,
    use_fast_breakout=True, fast_breakout_lookback=2, fast_breakout_mult=None,
    stall_exit_candles=STALL_CANDLES, stall_exit_min_peak_pct=STALL_MIN_PEAK,
    stall_exit_sl_pct=STALL_SL_PCT,
)

all_trades_combined = []


def run_one(symbol):
    bcl.SQUEEZE_ENTER_MULT = 0.7
    bcl.BREAKOUT_MULT = 1.6

    candles = bcl.fetch_klines(symbol, INTERVAL, DAYS)
    trades, seed_end = bcl.run_backtest(candles, **common_kwargs)

    print(f"\n{'='*60}\n[{symbol}]\n{'='*60}")
    print(f"총 거래수: {len(trades)}건")
    if not trades:
        print("거래 없음")
        return

    for t in trades:
        t["_symbol"] = symbol
    all_trades_combined.extend(trades)

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
        dt = datetime.fromtimestamp(ruin_ts / 1000)
        print(f"[!!] 복리 파산: 거래#{ruin_idx+1}/{len(trades)}, {dt} 시점에 시드 <= 0")
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


for sym in SYMBOLS:
    run_one(sym)

print(f"\n{'='*60}\n[전체 합산: BTC+ETH+XRP+SOL]\n{'='*60}")
if all_trades_combined:
    trades = sorted(all_trades_combined, key=lambda t: t["entry_ts"])
    wins = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] <= 0]
    win_rate = len(wins) / len(trades) * 100
    gross_win = sum(t["profit"] for t in wins)
    gross_loss = -sum(t["profit"] for t in losses)
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    avg_hold = sum(t["hold_h"] for t in trades) / len(trades)
    avg_pct = sum(t["pct"] for t in trades) / len(trades)
    sum_pct = sum(t["pct"] for t in trades)

    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1

    print(f"총 거래수: {len(trades)}건 (4개 심볼 합산, 시드 공유 가정 안 함 - 심볼별 독립 시드 기준 raw%만 합산)")
    print(f"[집계] 승률 {win_rate:.1f}%  PF {pf:.2f}  평균보유 {avg_hold:.1f}h")
    print(f"  거래당 평균 raw% {avg_pct:+.3f}%  비복리 단순합산% {sum_pct:+.1f}%")
    print("  종료사유:", ", ".join(f"{k} {v}건({v/len(trades)*100:.1f}%)" for k, v in reasons.items()))

    by_symbol = defaultdict(list)
    for t in trades:
        by_symbol[t["_symbol"]].append(t)
    print("\n| 심볼 | 거래수 | 승률 | PF | 비복리합산% |")
    print("|---|---|---|---|---|")
    for sym in SYMBOLS:
        st = by_symbol.get(sym, [])
        if not st:
            print(f"| {sym} | 0 | - | - | - |")
            continue
        swins = [t for t in st if t["profit"] > 0]
        slosses = [t for t in st if t["profit"] <= 0]
        s_win_rate = len(swins) / len(st) * 100
        s_gw = sum(t["profit"] for t in swins)
        s_gl = -sum(t["profit"] for t in slosses)
        s_pf = s_gw / s_gl if s_gl > 0 else float("inf")
        s_pf_str = f"{s_pf:.2f}" if s_pf != float("inf") else "inf"
        s_sum_pct = sum(t["pct"] for t in st)
        print(f"| {sym} | {len(st)} | {s_win_rate:.1f}% | {s_pf_str} | {s_sum_pct:+.1f}% |")

print("\n=== CURRENT LIVE 4-COIN (BTC/ETH/XRP/SOL) 2Y TEST COMPLETE ===", flush=True)
