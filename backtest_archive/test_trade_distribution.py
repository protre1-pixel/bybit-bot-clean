"""
2026-08-12: "대부분 쪼금쪼금씩 수익내서 중첩되는 전략인가, 한 번에 크게 먹는
전략인가?" 질문에 답하기 위해 실제 거래별 수익률(pct) 분포를 뽑아본다.
현재 라이브와 동일 조건(15분봉, sq=0.7/bo=1.6, HMA regime 필터)로 4코인 합산.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

bcl.SQUEEZE_ENTER_MULT = 0.7
bcl.BREAKOUT_MULT = 1.6

INTERVAL = "15"
DAYS = 730
COINS = ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]


def main():
    all_trades = []
    for sym in COINS:
        candles = bcl.fetch_klines(sym, INTERVAL, DAYS)
        trades, _ = bcl.run_backtest(candles, use_hma_regime_filter=True)
        all_trades.extend(trades)

    n = len(all_trades)
    pcts = sorted([t["pct"] for t in all_trades])
    # 승/패는 반드시 profit(수수료 반영 달러손익) 기준으로 - pct는 수수료 반영 전 순수 가격변동률이라
    # pct>0인데 수수료 빼면 실제 손실인 거래가 있어서 승/패 판정용으로 쓰면 안 됨 (2026-08-12 수정).
    win_trades = [t for t in all_trades if t["profit"] > 0]
    loss_trades = [t for t in all_trades if t["profit"] <= 0]
    wins = [t["pct"] for t in win_trades]
    losses = [t["pct"] for t in loss_trades]

    print(f"총 거래수: {n}  (승 {len(wins)} / 패 {len(losses)})  승률(profit기준): {len(wins)/n*100:.1f}%")
    print(f"평균 수익률(승): {sum(wins)/len(wins):+.3f}%   평균 수익률(패): {sum(losses)/len(losses):+.3f}%")
    print(f"중앙값 pct: {pcts[n//2]:+.3f}%")
    print(f"최대 수익 거래 top5: {[f'{p:+.2f}%' for p in pcts[-5:]]}")
    print(f"최대 손실 거래 top5: {[f'{p:+.2f}%' for p in pcts[:5]]}")

    # 수익구간별 분포
    buckets = [(-100, -3), (-3, -1), (-1, 0), (0, 0.3), (0.3, 0.6), (0.6, 1.0), (1.0, 2.0), (2.0, 5.0), (5.0, 100)]
    print("\n구간별 거래수:")
    for lo, hi in buckets:
        cnt = len([p for p in pcts if lo <= p < hi])
        print(f"  {lo:>6.1f}% ~ {hi:<6.1f}% : {cnt:>4}건  ({cnt/n*100:.1f}%)")

    # 상위 N% 거래가 전체 pct 합계의 몇 %를 차지하는가 (달러가 아니라 % 기준, 복리효과 배제하고 순수 분포만 보기 위함)
    total_pct = sum(pcts)
    sorted_by_abs_gain = sorted(pcts, reverse=True)
    for top_frac in [0.01, 0.05, 0.1, 0.2]:
        k = max(1, int(n * top_frac))
        top_sum = sum(sorted_by_abs_gain[:k])
        print(f"상위 {top_frac*100:.0f}%({k}건) 거래의 pct 합 / 전체 pct 합: {top_sum:.1f} / {total_pct:.1f} = {top_sum/total_pct*100:.1f}%")


if __name__ == "__main__":
    main()
