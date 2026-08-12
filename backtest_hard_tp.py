"""2026-08-11 실험: "진입가 대비 +1% 도달하면 단계 무관 무조건 즉시 익절"이 현재 방식보다 나은지 비교.

배경: 지금 익절이 원가+0.15%에서 자꾸 잘리는 문제(0.4%~2% 구간 보호장치 부재) 확인 후,
profit_lock_trigger를 낮추는 방향(backtest_profit_lock_early.py)은 검증 완료(개선 확인).
이번엔 아예 다른 접근 - "복잡한 단계별 트레일링 대신 그냥 1% 먹으면 무조건 나온다"는
제일 단순한 방식이 어떤지 확인.

sq=0.5, bo=1.5(현재 라이브), profit_lock 2.0/0.85(현재 라이브) 고정 위에 hard_tp_pct만 켬/끔 비교.
1h, 400일.

사용법: python backtest_hard_tp.py [SYMBOL] [DAYS] [SYMBOL2 ...]
"""
import sys

import backtest_current_live as bcl

DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else bcl.DAYS
PLT, PLR = 2.0, 0.85

VARIANTS = [
    ("현재라이브(hard_tp 없음)", None),
    ("hard_tp=1.0%", 1.0),
    ("hard_tp=1.5%", 1.5),
    ("hard_tp=0.8%", 0.8),
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
    avg_win_pct = sum(t["pct"] for t in wins) / len(wins) if wins else 0
    avg_loss_pct = sum(t["pct"] for t in losses) / len(losses) if losses else 0
    return (f"거래{n:>3}건 승률{win_rate:5.1f}% PF{pf:5.2f} 수익률{total_return:+8.2f}% "
            f"MDD{mdd:5.1f}%  평균익{avg_win_pct:+.2f}% 평균손{avg_loss_pct:+.2f}%")


if __name__ == "__main__":
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT", "ADAUSDT", "NEARUSDT"]

    bcl.SQUEEZE_ENTER_MULT = 0.5
    bcl.BREAKOUT_MULT = 1.5

    results = {label: [] for label, _ in VARIANTS}

    for sym in coins:
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 1시간봉 데이터 수집 중...", flush=True)
        candles = bcl.fetch_klines(sym, "60", DAYS)
        print(f"캔들 {len(candles)}개 수집 완료", flush=True)

        print(f"\n--- {sym} 무조건 익절(hard_tp) 비교 (sq=0.5 bo=1.5, profit_lock 2.0/0.85, 1h) ---")
        for label, htp in VARIANTS:
            trades, seed = bcl.run_backtest(candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
                                             hard_tp_pct=htp)
            total_return = (seed - bcl.SEED) / bcl.SEED * 100
            results[label].append(total_return)
            print(f"  {label}: {quick_stats(trades, seed)}", flush=True)

    print(f"\n\n=== 코인 평균 수익률 ===")
    for label, _ in VARIANTS:
        avg = sum(results[label]) / len(results[label]) if results[label] else 0
        print(f"  {label}: 평균 {avg:+.2f}%  (개별: {['%+.2f%%' % r for r in results[label]]})")

    print("\n\n=== HARD TP SWEEP COMPLETE ===", flush=True)
