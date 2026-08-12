"""2026-08-12 실험: 15분봉으로 XRP/SOL/ETH만 - 무조건 익절(hard_tp) 1.0%/0.7%/0.5% 재검증.

배경: backtest_hard_tp.py에서 1시간봉 기준으로 hard_tp(1.0/1.5/0.8%)를 테스트했더니
전부 기준선(hard_tp 없음)보다 나빴음(추세추종 큰 승리 트레이드를 잘라먹는 문제).
사용자가 "1시간봉 말고 15분봉으로, 1%/0.7%/0.5%로 다시" 요청.

주의: run_backtest()의 BB_PERIOD/HMA_ENTRY_PERIOD/HMA_GAP_FAST 등은 전부 "봉 개수"
기준 상수라, 캔들을 15분봉으로 바꾸면 실제 시간 기준 lookback이 1시간봉 대비 1/4로
줄어듦. 즉 "더 촘촘하게 체크"가 아니라 진입 시그널 자체가 달라지는 별도 실험임
(entry+exit 전부 15분봉 기준으로 재계산됨). sq=0.5, bo=1.5, profit_lock 2.0/0.85
(현재 라이브)는 고정.

사용법: python backtest_hard_tp_15m.py [SYMBOL] [DAYS] [SYMBOL2 ...]
"""
import sys

import backtest_current_live as bcl

DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else bcl.DAYS
PLT, PLR = 2.0, 0.85

VARIANTS = [
    ("현재라이브(hard_tp 없음)", None),
    ("hard_tp=1.0%", 1.0),
    ("hard_tp=0.7%", 0.7),
    ("hard_tp=0.5%", 0.5),
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
    return (f"거래{n:>4}건 승률{win_rate:5.1f}% PF{pf:5.2f} 수익률{total_return:+8.2f}% "
            f"MDD{mdd:5.1f}%  평균익{avg_win_pct:+.2f}% 평균손{avg_loss_pct:+.2f}%")


if __name__ == "__main__":
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["XRPUSDT", "SOLUSDT", "ETHUSDT"]

    bcl.SQUEEZE_ENTER_MULT = 0.5
    bcl.BREAKOUT_MULT = 1.5

    results = {label: [] for label, _ in VARIANTS}

    for sym in coins:
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 15분봉 데이터 수집 중...", flush=True)
        candles = bcl.fetch_klines(sym, "15", DAYS)
        print(f"캔들 {len(candles)}개 수집 완료", flush=True)

        print(f"\n--- {sym} 무조건 익절(hard_tp) 비교 (15분봉, sq=0.5 bo=1.5, profit_lock 2.0/0.85) ---")
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

    print("\n\n=== HARD TP 15M SWEEP COMPLETE ===", flush=True)
