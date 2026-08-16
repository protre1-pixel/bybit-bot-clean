"""
2026-08-14: XRP 1년치에서 확인한 HMA200/600 갭임계값 스윕 결과(0.2~0.3%가 가장 안정적)가
나머지 3코인(ETH/BTC/SOL)에서도 재현되는지 확인. 1년치(365일) 데이터로 진행(시간 절약).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

bcl.SQUEEZE_ENTER_MULT = 0.7
bcl.BREAKOUT_MULT = 1.6

INTERVAL = "15"
DAYS = 365
COINS = ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]
GAP_THRESHOLDS = [0.0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0]


def stats(trades):
    n = len(trades)
    if n == 0:
        return n, 0, 0, 0, 0
    wins = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] <= 0]
    win_rate = len(wins) / n * 100
    gross_win = sum(t["profit"] for t in wins)
    gross_loss = -sum(t["profit"] for t in losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    avg_hold = sum(t["hold_h"] for t in trades) / n

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
    return n, win_rate, pf, mdd, avg_hold


def main():
    per_coin_trades = {gap: [] for gap in GAP_THRESHOLDS}

    for sym in COINS:
        candles = bcl.fetch_klines(sym, INTERVAL, DAYS)
        print(f"\n[{sym}] 캔들 {len(candles)}개")
        print(f"{'갭임계값':>8} {'거래수':>6} {'승률':>7} {'PF':>6} {'MDD':>7} {'평균보유':>7}")
        for gap in GAP_THRESHOLDS:
            trades, _ = bcl.run_backtest(candles, use_hma_direction_only=True, hma_gap_min_pct=gap)
            per_coin_trades[gap].extend(trades)
            n, wr, pf, mdd, hold = stats(trades)
            print(f"{gap:>7.2f}% {n:>6} {wr:>6.1f}% {pf:>6.2f} {mdd:>6.1f}% {hold:>6.1f}h")

    print(f"\n{'='*60}\n4코인 합산\n{'='*60}")
    print(f"{'갭임계값':>8} {'거래수':>6} {'승률':>7} {'PF':>6} {'MDD':>7} {'평균보유':>7}")
    for gap in GAP_THRESHOLDS:
        n, wr, pf, mdd, hold = stats(per_coin_trades[gap])
        print(f"{gap:>7.2f}% {n:>6} {wr:>6.1f}% {pf:>6.2f} {mdd:>6.1f}% {hold:>6.1f}h")


if __name__ == "__main__":
    main()
