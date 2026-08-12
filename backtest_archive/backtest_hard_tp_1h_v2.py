"""2026-08-12 실험: "그냥 1% 먹으면 무조건 나온다" 전략 재검증 (1시간봉, 새 라이브 기준선).

배경: 예전(backtest_hard_tp.py)에 1h에서 hard_tp(1.0/1.5/0.8%)를 PROFIT_LOCK_TRIGGER=2.0%(구 라이브)
기준선과 비교했더니 전부 기준선보다 나빴음(추세추종 큰 승리 트레이드를 잘라먹는 문제).
그런데 그 사이 라이브 기준선 자체가 trigger=2.0% -> 0.5%로 바뀌었으므로(2026-08-12 배포),
새 기준선 대비로도 hard_tp가 여전히 손해인지 재확인.

사용자 요청: "상승추세든 하락추세든 타서 1%만 수익보고 나오는" 전략 - 진입 시그널(스퀴즈+HMA200 추세필터)은
기존 그대로 쓰고, 청산만 "무조건 +1%면 즉시 익절"로 바꿔서 비교. SL은 기존 동적 SL(BB폭 기반) 그대로 유지.

sq=0.5, bo=1.5(현재 라이브) 고정, profit_lock_trigger=0.5%, ratio=0.85(현재 라이브) 고정.
1h, 365일, XRP/ETH/BTC/SOL만(ADA/NEAR 제외).

사용법: python backtest_hard_tp_1h_v2.py [SYMBOL] [DAYS] [SYMBOL2 ...]
"""
import sys

import backtest_current_live as bcl

DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else bcl.DAYS
PLT, PLR = 0.5, 0.85  # 2026-08-12 배포된 새 라이브 기준값

VARIANTS = [
    ("현재라이브(hard_tp 없음, trigger=0.5%)", None),
    ("hard_tp=2.0%", 2.0),
    ("hard_tp=1.5%", 1.5),
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
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]

    bcl.SQUEEZE_ENTER_MULT = 0.5
    bcl.BREAKOUT_MULT = 1.5

    results = {label: [] for label, _ in VARIANTS}

    for sym in coins:
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 1시간봉 데이터 수집 중...", flush=True)
        candles = bcl.fetch_klines(sym, "60", DAYS)
        print(f"캔들 {len(candles)}개 수집 완료", flush=True)

        print(f"\n--- {sym} 무조건 익절(hard_tp) 비교 (1시간봉, sq=0.5 bo=1.5, profit_lock {PLT}/{PLR}) ---")
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

    print("\n\n=== HARD TP 1H (NEW BASELINE) SWEEP COMPLETE ===", flush=True)
