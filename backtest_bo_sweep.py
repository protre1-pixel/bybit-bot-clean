"""2026-08-11 실험: BREAKOUT_MULT(bo) 1.5 vs 2.0 비교.

배경: sq(SQUEEZE_ENTER_MULT)는 이미 0.4~1.0까지 광범위하게 스윕 완료. bo는 지금까지
모든 실험에서 1.5로 고정한 채 건드리지 않았음. 사용자가 "1.5는 낮은 것 같다"며 2.0으로
올렸을 때 효과를 확인 요청. sq=0.5(현재 라이브) 고정, profit_lock(2.0/0.85) 고정, 1h.

사용법: python backtest_bo_sweep.py [SYMBOL] [DAYS] [SYMBOL2 ...]
"""
import sys

import backtest_current_live as bcl

DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else bcl.DAYS
PLT, PLR = 2.0, 0.85
SQ = 0.5

BO_VALUES = [1.5, 2.0]


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
    avg_win_pct = sum(t["pct"] for t in wins) / len(wins) if wins else 0
    avg_loss_pct = sum(t["pct"] for t in losses) / len(losses) if losses else 0
    return (f"거래{n:>3}건 승률{win_rate:5.1f}% PF{pf:5.2f} 수익률{total_return:+8.2f}% "
            f"MDD{mdd:5.1f}%  평균익{avg_win_pct:+.2f}% 평균손{avg_loss_pct:+.2f}%")


if __name__ == "__main__":
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT", "ADAUSDT", "NEARUSDT"]

    results = {bo: [] for bo in BO_VALUES}

    bcl.SQUEEZE_ENTER_MULT = SQ

    for sym in coins:
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 1시간봉 데이터 수집 중...", flush=True)
        candles = bcl.fetch_klines(sym, "60", DAYS)
        print(f"캔들 {len(candles)}개 수집 완료", flush=True)

        print(f"\n--- {sym} BREAKOUT_MULT 비교 (sq={SQ}, 1h, profit_lock 2.0/0.85) ---")
        for bo in BO_VALUES:
            bcl.BREAKOUT_MULT = bo
            trades, seed = bcl.run_backtest(candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR)
            total_return = (seed - bcl.SEED) / bcl.SEED * 100
            results[bo].append(total_return)
            print(f"  bo={bo}: {quick_stats(trades, seed)}", flush=True)

    print(f"\n\n=== 코인 평균 수익률 ===")
    for bo in BO_VALUES:
        avg = sum(results[bo]) / len(results[bo]) if results[bo] else 0
        print(f"  bo={bo}: 평균 {avg:+.2f}%  (개별: {['%+.2f%%' % r for r in results[bo]]})")

    print("\n\n=== BO SWEEP COMPLETE ===", flush=True)
