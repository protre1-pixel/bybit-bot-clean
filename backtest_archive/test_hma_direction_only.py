"""
2026-08-14 실험: "브레이크아웃 캔들 방향(양봉/음봉)으로 신호 방향을 정하고, HMA200/600
정배열과 반대면 취소" 하던 기존 방식 대신, 캔들 방향은 아예 무시하고 브레이크아웃이 뜬
순간의 HMA200/600 정배열 상태로 바로 방향을 결정(up→롱, down→숏)하면 어떻게 되는지 검증.

사용자 요청: "지금은 캔들이 양봉인데 hma가 역배열이면 취소되고 음봉인데 정배열이면 취소되고
하는거자나? 그런거 없이 테스트 한번해줘 15분봉으로" (XRP 단일 코인 우선 검증)

기존(현재 라이브, use_hma_regime_filter=True) vs 신규(use_hma_direction_only=True) 비교.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

bcl.SQUEEZE_ENTER_MULT = 0.7
bcl.BREAKOUT_MULT = 1.6

INTERVAL = "15"
DAYS = 730
SYMBOL = "XRPUSDT"


def main():
    candles = bcl.fetch_klines(SYMBOL, INTERVAL, DAYS)
    print(f"[{SYMBOL}] 캔들 {len(candles)}개 "
          f"({bcl.datetime.fromtimestamp(candles[0]['ts']/1000)} ~ {bcl.datetime.fromtimestamp(candles[-1]['ts']/1000)})")

    trades_base, seed_base = bcl.run_backtest(candles, use_hma_regime_filter=True)
    bcl.summarize(f"{SYMBOL} 기존(캔들방향 + HMA regime 필터, 현재 라이브)", trades_base, seed_base)

    trades_new, seed_new = bcl.run_backtest(candles, use_hma_direction_only=True)
    bcl.summarize(f"{SYMBOL} 신규(캔들무시, HMA regime로 방향 직접 결정)", trades_new, seed_new)


if __name__ == "__main__":
    main()
