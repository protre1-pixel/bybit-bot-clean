"""2026-08-12 실험: backtest_profit_lock_early.py를 15분봉으로 재현.
sq=0.5, bo=1.5(현재 라이브), ratio=0.85 고정, trigger만 스윕.
ADA/NEAR는 계속 나빴던 코인이라 제외 - XRP/ETH/BTC/SOL만.

주의: 15분봉으로 바꾸면 BB_PERIOD/HMA200/HMA600 등 "봉 개수" 기준 지표들의 실제 시간
lookback이 1시간봉 대비 1/4로 줄어듦 - hard_tp_15m 실험에서 이미 확인했듯 진입 자체가
노이즈에 취약해질 수 있음. 그래도 profit_lock trigger 효과가 15분봉에서도 같은 방향으로
나오는지 확인 목적.

사용법: python backtest_profit_lock_early_15m.py [SYMBOL] [DAYS] [SYMBOL2 ...]
"""
import sys

import backtest_current_live as bcl

DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else bcl.DAYS
RATIO = 0.85

TRIGGERS = [2.0, 1.0, 0.8, 0.6, 0.5]


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
    return (f"거래{n:>4}건 승률{win_rate:5.1f}% PF{pf:5.2f} 수익률{total_return:+9.2f}% "
            f"MDD{mdd:5.1f}%  평균익{avg_win_pct:+.2f}% 평균손{avg_loss_pct:+.2f}%")


if __name__ == "__main__":
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]

    bcl.SQUEEZE_ENTER_MULT = 0.5
    bcl.BREAKOUT_MULT = 1.5

    results = {trg: [] for trg in TRIGGERS}

    for sym in coins:
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 15분봉 데이터 수집 중...", flush=True)
        candles = bcl.fetch_klines(sym, "15", DAYS)
        print(f"캔들 {len(candles)}개 수집 완료", flush=True)

        print(f"\n--- {sym} PROFIT_LOCK_TRIGGER 비교 (15분봉, sq=0.5 bo=1.5, ratio={RATIO}) ---")
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

    print("\n\n=== PROFIT LOCK EARLY-TRIGGER 15M SWEEP COMPLETE ===", flush=True)
