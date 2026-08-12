"""2026-08-12 실험: backtest_adx_trend.py(ADX방향+고정TP/SL) 기준선이 -100%로 전멸한 뒤,
사용자 요청으로 두 가지 개선 후보를 같이 스윕:
  1) ADX_MIN을 20→25→30으로 올려서 "진짜 확실한 추세"만 걸러지는지
  2) TP/SL을 비대칭(예: TP1.5%/SL1.0%)으로 바꿔서 승률 49%가 유지돼도 손익비로 커버되는지

ADX_MIN 3개 x TP/SL 조합(1.0/1.0 대칭 기준선 + 1.5/1.0, 2.0/1.0 비대칭) 전체 조합을 SOL만 테스트.

사용법: python backtest_adx_trend_sweep.py [SYMBOL] [DAYS] [SYMBOL2 ...]
"""
import sys

import backtest_adx_trend as adxt
import backtest_current_live as bcl

DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else bcl.DAYS

ADX_VALUES = [20, 25, 30]
TP_SL_VARIANTS = [
    ("1.0/1.0(대칭 기준선)", 1.0, 1.0),
    ("1.5/1.0(비대칭)", 1.5, 1.0),
    ("2.0/1.0(비대칭)", 2.0, 1.0),
]


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
    long_n = len([t for t in trades if t["side"] == "long"])
    short_n = len([t for t in trades if t["side"] == "short"])
    return (f"거래{n:>5}건(롱{long_n}/숏{short_n}) 승률{win_rate:5.1f}% PF{pf:5.2f} "
            f"수익률{total_return:+9.2f}% MDD{mdd:6.1f}%")


if __name__ == "__main__":
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["SOLUSDT"]

    for sym in coins:
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 1시간봉 데이터 수집 중...", flush=True)
        candles = bcl.fetch_klines(sym, "60", DAYS)
        print(f"캔들 {len(candles)}개 수집 완료", flush=True)

        print(f"\n--- {sym} ADX_MIN x TP/SL 스윕 ---")
        for adx_min in ADX_VALUES:
            for label, tp, sl in TP_SL_VARIANTS:
                trades, seed = adxt.run_backtest_adx_trend(candles, adx_min=adx_min, tp_pct=tp, sl_pct=sl)
                print(f"  ADX>={adx_min:>2} TP/SL={label}: {quick_stats(trades, seed)}", flush=True)

    print("\n\n=== ADX TREND SWEEP COMPLETE ===", flush=True)
