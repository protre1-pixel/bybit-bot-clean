"""
2026-08-14 실험: HMA200/600 부호(+/-)만으로 방향을 정하면 두 선이 거의 붙어있는
(추세가 약한/막 뒤집힌) 구간에서도 진입하는 노이즈가 낀다는 지적에 따라, 갭 크기
(|HMA200-HMA600| / 현재가 x 100, %) 최소 임계값을 스윕하며 어느 지점이 최적인지 탐색.

앞으로 백테스트는 시간 절약을 위해 1년치(365일) 데이터로 진행.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

bcl.SQUEEZE_ENTER_MULT = 0.7
bcl.BREAKOUT_MULT = 1.6

INTERVAL = "15"
DAYS = 365
SYMBOL = "XRPUSDT"

GAP_THRESHOLDS = [0.0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0]


def main():
    candles = bcl.fetch_klines(SYMBOL, INTERVAL, DAYS)
    print(f"[{SYMBOL}] 캔들 {len(candles)}개 "
          f"({bcl.datetime.fromtimestamp(candles[0]['ts']/1000)} ~ {bcl.datetime.fromtimestamp(candles[-1]['ts']/1000)})")

    print(f"\n{'갭임계값':>8} {'거래수':>6} {'승률':>7} {'PF':>6} {'MDD':>7} {'평균보유':>7}")
    for gap in GAP_THRESHOLDS:
        trades, seed = bcl.run_backtest(candles, use_hma_direction_only=True, hma_gap_min_pct=gap)
        n = len(trades)
        if n == 0:
            print(f"{gap:>7.2f}% {'거래없음':>6}")
            continue
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

        print(f"{gap:>7.2f}% {n:>6} {win_rate:>6.1f}% {pf:>6.2f} {mdd:>6.1f}% {avg_hold:>6.1f}h")


if __name__ == "__main__":
    main()
