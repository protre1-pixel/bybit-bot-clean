"""2026-08-11 실험: 익절 캡(0.04%) 문제 진단 후 PROFIT_LOCK_TRIGGER_PCT를 낮춰서 개선되는지 검증.

배경: 실거래에서 이긴 거래들이 전부 정확히 원가+0.15%(STAGE1_FEE_BUFFER_PCT)에서 잘리는 게
확인됨. peak_profit_pct가 0.4%~2.0% 사이인 거래는 "본전 바닥"(entry+0.15%, 고정값) 말고는
보호장치가 없고, "최고수익 반납방지"(profit_lock)는 2.0% 넘어야만 작동하기 때문.
반면 손절은 SL_PERCENT(3.5%) 상한까지 열려있어 손익비가 구조적으로 불리함
(필요승률 = 3.11/(3.11+0.04) = 98.7%).

가설: PROFIT_LOCK_TRIGGER_PCT를 낮추면(더 일찍 최고수익 비례 SL이 걸리면) 평균 익절폭이
커져서 손익비/PF가 개선될 것.

sq=0.5, bo=1.5(현재 라이브) 고정, ratio=0.85 고정, trigger만 스윕.
1h, 400일.

사용법: python backtest_profit_lock_early.py [SYMBOL] [DAYS] [SYMBOL2 ...]
"""
import sys

import backtest_current_live as bcl

DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else bcl.DAYS
RATIO = 0.85

TRIGGERS = [2.0, 1.0, 0.8, 0.6, 0.5]  # 2.0 = 현재 라이브(기준선)


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

    bcl.SQUEEZE_ENTER_MULT = 0.5
    bcl.BREAKOUT_MULT = 1.5

    results = {trg: [] for trg in TRIGGERS}

    for sym in coins:
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 1시간봉 데이터 수집 중...", flush=True)
        candles = bcl.fetch_klines(sym, "60", DAYS)
        print(f"캔들 {len(candles)}개 수집 완료", flush=True)

        print(f"\n--- {sym} PROFIT_LOCK_TRIGGER 비교 (sq=0.5 bo=1.5, ratio={RATIO}, 1h) ---")
        for trg in TRIGGERS:
            trades, seed = bcl.run_backtest(candles, profit_lock_trigger_pct=trg, profit_lock_ratio=RATIO)
            total_return = (seed - bcl.SEED) / bcl.SEED * 100
            results[trg].append(total_return)
            label = f"trigger={trg}%" + ("(현재라이브)" if trg == 2.0 else "")
            print(f"  {label}: {quick_stats(trades, seed)}", flush=True)

    print(f"\n\n=== 코인 평균 수익률 ===")
    for trg in TRIGGERS:
        avg = sum(results[trg]) / len(results[trg]) if results[trg] else 0
        label = f"trigger={trg}%" + ("(현재라이브)" if trg == 2.0 else "")
        print(f"  {label}: 평균 {avg:+.2f}%  (개별: {['%+.2f%%' % r for r in results[trg]]})")

    print("\n\n=== PROFIT LOCK EARLY-TRIGGER SWEEP COMPLETE ===", flush=True)
