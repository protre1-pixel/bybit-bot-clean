"""
2026-08-19(37차): 36차(SQ0.85/BO1.3 + 레버10x + 홀드1h + SL8.5%)가 PF 1.46~1.65, MDD
33.6~69.6%로 전 종목 대폭 악화되어 배포 보류함. 원인으로 "홀드1h가 너무 짧아서 승리
거래가 무르익기 전에 정상 청산 로직에 걸려 조기 이탈"을 지목했었는데, 이를 검증하기 위해
사용자가 "홀드없이 테스트 해봐"라고 요청 - 즉 홀드window 자체를 아예 빼고(min_hold 개념
없이) 진입 직후부터 정상 SL/TP/stall_exit/HMA200-Break 등 라이브의 기존 청산 로직이 바로
적용되는 순정 run_backtest()로 SQ0.85/BO1.3 + 레버10x만 테스트. 레버리지는 AskUserQuestion으로
확인(10x 선택, 직전 요청과 동일하게 유지).

방법: 하이브리드 몽키패치(min_hold_candles/hold_cat_sl_pct) 전혀 사용 안 하고, bcl.run_backtest를
그대로 호출. bcl.SQUEEZE_ENTER_MULT=0.85, bcl.BREAKOUT_MULT=1.3, bcl.LEVERAGE=10만 바꿈.
LIVE_KWARGS(profit_lock/stall_exit/hma_direction/fast_breakout/regime_exit 등)는 34~36차와 동일.

비교 대상:
1) CURRENT_LIVE(34차, SQ0.7/BO1.6 + 레버5x/홀드3h/SL16%, 실제 배포 근거):
   BTC n=227 승률67.8% PF2.67 MDD8.9% 비복리+141.6%
   ETH n=239 승률64.4% PF2.99 MDD9.5% 비복리+218.6%
   XRP n=220 승률75.0% PF4.92 MDD12.8% 비복리+188.2%
   SOL n=251 승률69.3% PF3.88 MDD20.8% 비복리+228.5%
2) SQ085_BO13_LEV5_3H_16SL(35차, SQ0.85/BO1.3 + 레버5x/홀드3h/SL16%):
   BTC n=359 승률63.8% PF2.43 MDD14.6% 비복리+190.7%
   ETH n=367 승률66.8% PF3.57 MDD18.4% 비복리+314.3%
   XRP n=364 승률67.6% PF3.19 MDD13.2% 비복리+293.3%
   SOL n=369 승률68.8% PF3.36 MDD14.7% 비복리+345.3%
3) SQ085_BO13_LEV10_1H_85SL(36차, SQ0.85/BO1.3 + 레버10x/홀드1h/SL8.5%, 배포보류):
   BTC n=392 승률61.7% PF1.46 MDD33.6% 비복리+109.6%
   ETH n=406 승률62.1% PF1.65 MDD41.0% 비복리+158.2%
   XRP n=391 승률62.4% PF1.49 MDD36.0% 비복리+172.4%
   SOL n=414 승률66.2% PF1.47 MDD69.6% 비복리+195.5% 캣SL2건

스코프: BTCUSDT/ETHUSDT/XRPUSDT/SOLUSDT, 15분봉, 365일.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT"]
INTERVAL = "15"
DAYS = 365
TEST_LEVERAGE = 10

NEW_SQUEEZE_ENTER_MULT = 0.85
NEW_BREAKOUT_MULT = 1.3

LIVE_KWARGS = dict(
    profit_lock_trigger_pct=0.5,
    profit_lock_ratio=1.0,
    use_price_alignment_filter=True,
    stall_exit_candles=8, stall_exit_min_peak_pct=0.5,
    stall_exit_sl_pct=0.4,
    use_hma_direction_only=True,
    use_fast_breakout=True, fast_breakout_lookback=2, fast_breakout_mult=None,
    use_regime_exit=True,
)

CURRENT_LIVE = {
    "BTCUSDT": dict(n=227, win_rate=67.8, pf=2.67, mdd=8.9, sum_pct=141.6, cat_sl_count=0),
    "ETHUSDT": dict(n=239, win_rate=64.4, pf=2.99, mdd=9.5, sum_pct=218.6, cat_sl_count=0),
    "XRPUSDT": dict(n=220, win_rate=75.0, pf=4.92, mdd=12.8, sum_pct=188.2, cat_sl_count=0),
    "SOLUSDT": dict(n=251, win_rate=69.3, pf=3.88, mdd=20.8, sum_pct=228.5, cat_sl_count=0),
}

SQ085_BO13_LEV5_3H_16SL = {
    "BTCUSDT": dict(n=359, win_rate=63.8, pf=2.43, mdd=14.6, sum_pct=190.7, cat_sl_count=0),
    "ETHUSDT": dict(n=367, win_rate=66.8, pf=3.57, mdd=18.4, sum_pct=314.3, cat_sl_count=0),
    "XRPUSDT": dict(n=364, win_rate=67.6, pf=3.19, mdd=13.2, sum_pct=293.3, cat_sl_count=0),
    "SOLUSDT": dict(n=369, win_rate=68.8, pf=3.36, mdd=14.7, sum_pct=345.3, cat_sl_count=0),
}

SQ085_BO13_LEV10_1H_85SL = {
    "BTCUSDT": dict(n=392, win_rate=61.7, pf=1.46, mdd=33.6, sum_pct=109.6, cat_sl_count=0),
    "ETHUSDT": dict(n=406, win_rate=62.1, pf=1.65, mdd=41.0, sum_pct=158.2, cat_sl_count=0),
    "XRPUSDT": dict(n=391, win_rate=62.4, pf=1.49, mdd=36.0, sum_pct=172.4, cat_sl_count=0),
    "SOLUSDT": dict(n=414, win_rate=66.2, pf=1.47, mdd=69.6, sum_pct=195.5, cat_sl_count=2),
}


def summarize(trades, seed_end):
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
    sum_pct = sum(t["pct"] for t in trades)

    cat_sl_count = sum(1 for t in trades if t["reason"] == "Catastrophic SL (hold)")

    return dict(n=len(trades), win_rate=win_rate, pf=pf, mdd=mdd, avg_hold=avg_hold,
                sum_pct=sum_pct, total_return=total_return, cat_sl_count=cat_sl_count)


results = {}

for symbol in SYMBOLS:
    print(f"\n{'#'*60}\n# {symbol}\n{'#'*60}")
    bcl.SQUEEZE_ENTER_MULT = NEW_SQUEEZE_ENTER_MULT
    bcl.BREAKOUT_MULT = NEW_BREAKOUT_MULT
    bcl.LEVERAGE = TEST_LEVERAGE
    candles = bcl.fetch_klines(symbol, INTERVAL, DAYS)

    trades, seed_end = bcl.run_backtest(candles, **LIVE_KWARGS)
    s = summarize(trades, seed_end)
    results[symbol] = s

    print(f"[{symbol}/SQ0.85_BO1.3_LEV10_NOHOLD] 거래수 {s['n']}건  승률 {s['win_rate']:.1f}%  "
          f"PF {s['pf']:.2f}  MDD {s['mdd']:.1f}%  평균보유 {s['avg_hold']:.1f}h  "
          f"비복리합산 {s['sum_pct']:+.1f}%  캐터스트로픽SL발동 {s['cat_sl_count']}건", flush=True)

print(f"\n{'='*100}\n[종합: 현재라이브(0.7/1.6,5x,3h,16%) vs 35차(0.85/1.3,5x,3h,16%) vs "
      f"36차(0.85/1.3,10x,1h,8.5%) vs 37차-신규(0.85/1.3,10x,홀드없음)]\n{'='*100}")
print("| 심볼 | 버전 | 거래수 | 승률 | PF | MDD | 비복리합산% | 캣SL발동 |")
print("|---|---|---|---|---|---|---|---|")
for symbol in SYMBOLS:
    c = CURRENT_LIVE[symbol]
    m5 = SQ085_BO13_LEV5_3H_16SL[symbol]
    m10 = SQ085_BO13_LEV10_1H_85SL[symbol]
    n = results[symbol]
    pfn = f"{n['pf']:.2f}" if n['pf'] != float("inf") else "inf"
    print(f"| {symbol} | 현재라이브(0.7/1.6,5x,3h,16%) | {c['n']} | {c['win_rate']:.1f}% | {c['pf']:.2f} | "
          f"{c['mdd']:.1f}% | {c['sum_pct']:+.1f}% | {c['cat_sl_count']}건 |")
    print(f"| {symbol} | 35차(0.85/1.3,5x,3h,16%) | {m5['n']} | {m5['win_rate']:.1f}% | {m5['pf']:.2f} | "
          f"{m5['mdd']:.1f}% | {m5['sum_pct']:+.1f}% | {m5['cat_sl_count']}건 |")
    print(f"| {symbol} | 36차(0.85/1.3,10x,1h,8.5%) | {m10['n']} | {m10['win_rate']:.1f}% | {m10['pf']:.2f} | "
          f"{m10['mdd']:.1f}% | {m10['sum_pct']:+.1f}% | {m10['cat_sl_count']}건 |")
    print(f"| {symbol} | 37차(0.85/1.3,10x,홀드없음) | {n['n']} | {n['win_rate']:.1f}% | {pfn} | "
          f"{n['mdd']:.1f}% | {n['sum_pct']:+.1f}% | {n['cat_sl_count']}건 |")

print("\n=== SQ0.85/BO1.3 (LEVERAGE 10x, NO HOLD WINDOW) 4-COIN 1Y TEST COMPLETE ===", flush=True)
