"""
2026-08-14: 지금까지 갭임계값 스윕은 전부 use_hma_direction_only=True(HMA 부호로 방향
자체를 결정)로 테스트했는데, 이건 실전(trading_service.py apply_entry_filters)과 다른
로직임 - 실전은 "캔들 몸통(양봉/음봉)으로 방향 먼저 결정 + HMA200/600 정배열이 그 방향과
일치해야 진입"(use_hma_regime_filter=True). 사용자 판단 - "캔들방향을 그대로 쓰자" →
실전과 동일한 로직에 갭크기 필터만 추가해서 재검증. backtest_current_live.py의
use_hma_regime_filter 분기에 hma_gap_min_pct 훅을 새로 연결(기존엔 없었음).

XRP+ETH+BTC+SOL, 15분봉, 365일.
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
        print(f"\n[{sym}] 캔들 {len(candles)}개 (실전 로직: 캔들방향+HMA정배열 필터)")
        print(f"{'갭임계값':>8} {'거래수':>6} {'승률':>7} {'PF':>6} {'MDD':>7} {'평균보유':>7}")
        for gap in GAP_THRESHOLDS:
            trades, _ = bcl.run_backtest(candles, use_hma_regime_filter=True, hma_gap_min_pct=gap)
            per_coin_trades[gap].extend(trades)
            n, wr, pf, mdd, hold = stats(trades)
            print(f"{gap:>7.2f}% {n:>6} {wr:>6.1f}% {pf:>6.2f} {mdd:>6.1f}% {hold:>6.1f}h")

    print(f"\n{'='*60}\n4코인 합산 (실전 로직)\n{'='*60}")
    print(f"{'갭임계값':>8} {'거래수':>6} {'승률':>7} {'PF':>6} {'MDD':>7} {'평균보유':>7}")
    for gap in GAP_THRESHOLDS:
        n, wr, pf, mdd, hold = stats(per_coin_trades[gap])
        print(f"{gap:>7.2f}% {n:>6} {wr:>6.1f}% {pf:>6.2f} {mdd:>6.1f}% {hold:>6.1f}h")


if __name__ == "__main__":
    main()
