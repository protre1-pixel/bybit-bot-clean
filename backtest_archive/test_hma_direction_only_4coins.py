"""
2026-08-14 실험 (XRP 단일 코인에서 확인한 결과를 4코인 합산으로 검증):
브레이크아웃 캔들 방향(양봉/음봉)으로 신호 방향을 정하고 HMA200/600 정배열과
반대면 취소하던 기존 방식 대신, 캔들 방향은 아예 무시하고 브레이크아웃이 뜬 순간의
HMA200/600 정배열 상태로 바로 방향을 결정(up→롱, down→숏)하는 방식을 비교.

XRP 단독 결과(거래수 454→878, 승률 80.2%→86.3%, PF 2.00→2.49, MDD 54.56%→45.06%)가
4코인 합산(XRP/ETH/BTC/SOL)에서도 재현되는지 확인.
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


def combine(all_trades_list):
    combined = []
    for trades in all_trades_list:
        combined.extend(trades)
    return combined


def main():
    base_all = []
    new_all = []

    for sym in COINS:
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 {INTERVAL}분봉 데이터 수집 중...")
        candles = bcl.fetch_klines(sym, INTERVAL, DAYS)
        print(f"캔들 {len(candles)}개 수집 완료")

        trades_base, seed_base = bcl.run_backtest(candles, use_hma_regime_filter=True)
        bcl.summarize(f"{sym} [기존] 캔들방향 + HMA regime 필터 (현재 라이브)", trades_base, seed_base)
        base_all.append(trades_base)

        trades_new, seed_new = bcl.run_backtest(candles, use_hma_direction_only=True)
        bcl.summarize(f"{sym} [신규] 캔들무시, HMA regime로 방향 직접 결정", trades_new, seed_new)
        new_all.append(trades_new)

    print(f"\n\n{'='*70}\n전체 4코인 합산 비교\n{'='*70}")
    bcl.summarize("[기존] 캔들방향 + HMA regime 필터 - 전체합산", combine(base_all), bcl.SEED)
    bcl.summarize("[신규] 캔들무시, HMA regime로 방향 직접 결정 - 전체합산", combine(new_all), bcl.SEED)


if __name__ == "__main__":
    main()
