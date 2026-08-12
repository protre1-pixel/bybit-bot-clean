"""2026-08-12: 현재 라이브 설정(sq=0.5, bo=1.5, profit_lock trigger=0.5%/ratio=0.85, 1h)을
그대로 두고 ENTRY_PERCENT만 0.75 -> 1.0(계좌 100% 투입)으로 바꿔서 비교.

사용법: python backtest_100pct_verify.py [SYMBOL] [DAYS] [SYMBOL2 ...]
"""
import sys

import backtest_current_live as bcl

DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else bcl.DAYS
PLT, PLR = 0.5, 0.85


def quick_stats(trades, final_seed):
    n = len(trades)
    if n == 0:
        return "거래 없음"
    wins = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] <= 0]
    win_rate = len(wins) / n * 100
    gross_win = sum(t["profit"] for t in wins)
    gross_loss = -sum(t["profit"] for t in losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    total_return = (final_seed - bcl.SEED) / bcl.SEED * 100
    curve = [bcl.SEED]
    s = bcl.SEED
    for t in trades:
        s += t["profit"]
        curve.append(s)
    peak = curve[0]
    mdd = 0
    for v in curve:
        peak = max(peak, v)
        dd = (peak - v) / peak * 100 if peak > 0 else 0
        mdd = max(mdd, dd)
    return (f"거래{n:>3}건 승률{win_rate:5.1f}% PF{pf:5.2f} 수익률{total_return:+9.2f}% "
            f"MDD{mdd:5.1f}%  최종잔고 ${final_seed:,.2f}")


if __name__ == "__main__":
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]

    bcl.SQUEEZE_ENTER_MULT = 0.5
    bcl.BREAKOUT_MULT = 1.5

    for entry_pct, label in [(0.75, "ENTRY_PERCENT=75%(현재라이브)"), (1.0, "ENTRY_PERCENT=100%")]:
        bcl.ENTRY_PERCENT = entry_pct
        print(f"\n{'='*70}\n[{label}]", flush=True)
        totals = []
        for sym in coins:
            candles = bcl.fetch_klines(sym, "60", DAYS)
            trades, seed = bcl.run_backtest(candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR)
            total_return = (seed - bcl.SEED) / bcl.SEED * 100
            totals.append((sym, total_return, seed))
            print(f"  {sym}: {quick_stats(trades, seed)}", flush=True)
        avg = sum(t[1] for t in totals) / len(totals)
        sum_final = sum(t[2] for t in totals)
        sum_seed = bcl.SEED * len(totals)
        print(f"  -> 평균 수익률 {avg:+.2f}%  |  합산 시드 ${sum_seed:,.0f} -> ${sum_final:,.2f} "
              f"(합산 수익금 +${sum_final - sum_seed:,.2f})")

    print("\n\n=== 100% ENTRY VERIFY COMPLETE ===", flush=True)
