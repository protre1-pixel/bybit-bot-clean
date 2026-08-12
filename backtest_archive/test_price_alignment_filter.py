"""
2026-08-12 실험: 진입 필터를 "HMA200/600 regime만" 대신
"가격/200/600 완전 정배열(역배열)"로 바꿨을 때 결과 비교.

롱: 가격 > HMA200 > HMA600 일 때만 진입
숏: HMA600 > HMA200 > 가격 일 때만 진입

현재 라이브(15분봉, sq=0.7, bo=1.6, HMA regime 필터)와
직접 비교하기 위해 동일 데이터/파라미터로 두 필터를 나란히 돌림.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

# 현재 라이브 파라미터로 맞춤 (2026-08-12 기준: 15분봉, sq=0.7, bo=1.6)
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
    regime_all = []
    align_all = []

    for sym in COINS:
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 {INTERVAL}분봉 데이터 수집 중...")
        candles = bcl.fetch_klines(sym, INTERVAL, DAYS)
        print(f"캔들 {len(candles)}개 수집 완료")

        trades_regime, seed_regime = bcl.run_backtest(candles, use_hma_regime_filter=True)
        bcl.summarize(f"{sym} [기존] HMA regime 필터 (200/600 정배열만, 가격위치 무관)", trades_regime, seed_regime)
        regime_all.append(trades_regime)

        trades_align, seed_align = bcl.run_backtest(candles, use_price_alignment_filter=True)
        bcl.summarize(f"{sym} [신규] 가격/200/600 완전정배열 필터", trades_align, seed_align)
        align_all.append(trades_align)

    print(f"\n\n{'='*70}\n전체 4코인 합산 비교\n{'='*70}")
    bcl.summarize("[기존] HMA regime 필터 - 전체합산", combine(regime_all), bcl.SEED)
    bcl.summarize("[신규] 가격/200/600 완전정배열 필터 - 전체합산", combine(align_all), bcl.SEED)


if __name__ == "__main__":
    main()
