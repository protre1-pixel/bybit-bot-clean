"""2026-08-12 실험: 진입필터를 "가격 vs HMA200"에서 "HMA200 vs HMA600 정배열/역배열"로 교체.

사용자 요청: "캔들이 롱신호인데 200/600일선이 정방향이야(정배열) - 가격이 200일보다 아래
있어도 롱 진입하고, 숏은 그 반대." 즉 눌림목(가격이 일시적으로 200선 아래로 빠진 구간)에서도
큰 추세(HMA200/600 골든/데드크로스)가 살아있으면 진입을 허용하는 방향.

현재 라이브 설정(sq=0.5, bo=1.5, profit_lock trigger=0.5%/ratio=0.85, 1h) 고정하고
진입필터만 교체해서 비교. 1h, 365일, XRP/ETH/BTC/SOL만.

사용법: python backtest_hma_regime_filter.py [SYMBOL] [DAYS] [SYMBOL2 ...]
"""
import os
import sys

import backtest_current_live as bcl

DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else bcl.DAYS
INTERVAL = os.environ.get("REGIME_INTERVAL", "60")
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


VARIANTS = [
    ("현재라이브(가격 vs HMA200)", False),
    ("신규(HMA200 vs HMA600 정배열/역배열)", True),
]

if __name__ == "__main__":
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]

    bcl.SQUEEZE_ENTER_MULT = 0.5
    bcl.BREAKOUT_MULT = 1.5

    results = {label: [] for label, _ in VARIANTS}

    for sym in coins:
        tf_label = "1시간봉" if INTERVAL == "60" else f"{INTERVAL}분봉"
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 {tf_label} 데이터 수집 중...", flush=True)
        candles = bcl.fetch_klines(sym, INTERVAL, DAYS)
        print(f"캔들 {len(candles)}개 수집 완료", flush=True)

        print(f"\n--- {sym} 진입필터 비교 ({tf_label}, sq=0.5 bo=1.5, profit_lock {PLT}/{PLR}) ---")
        for label, use_regime in VARIANTS:
            trades, seed = bcl.run_backtest(candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
                                             use_hma_regime_filter=use_regime)
            total_return = (seed - bcl.SEED) / bcl.SEED * 100
            results[label].append((total_return, seed))
            print(f"  {label}: {quick_stats(trades, seed)}", flush=True)

    print(f"\n\n=== 코인 평균 수익률 ===")
    for label, _ in VARIANTS:
        rets = [r for r, s in results[label]]
        finals = [s for r, s in results[label]]
        avg = sum(rets) / len(rets) if rets else 0
        sum_final = sum(finals)
        sum_seed = bcl.SEED * len(finals)
        print(f"  {label}: 평균 {avg:+.2f}%  |  합산 ${sum_seed:,.0f} -> ${sum_final:,.2f} "
              f"(개별: {['%+.2f%%' % r for r in rets]})")

    print("\n\n=== HMA REGIME FILTER COMPARE COMPLETE ===", flush=True)
