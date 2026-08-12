"""2026-08-11 실험: 스퀴즈+HMA200 전략에 ADX(14) 레짐필터를 얹었을 때 효과 검증.

가설: BTC/ADA/NEAR가 sq/bo 임계값을 아무리 바꿔도 계속 나빴던 이유가, 이 코인들의
스퀴즈+돌파 신호 상당수가 사실 횡보(레인지)장 안에서의 노이즈성 가짜 돌파이기
때문일 수 있다. ADX가 낮은(추세가 약한) 시점의 신호를 걸러내면 승률/PF가
개선되는지, 특히 지금까지 계속 나빴던 코인들에서 개선되는지 확인.

현재 라이브 값(sq=0.5, bo=1.5) 고정, profit_lock(2.0/0.85) 고정, 1시간봉.
adx_min=None(미적용, 현재 라이브)과 15/20/25/30을 비교.

사용법: python backtest_adx_filter.py [SYMBOL] [DAYS] [SYMBOL2 ...]
"""
import sys
from datetime import datetime

import backtest_current_live as bcl

DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else bcl.DAYS
PLT, PLR = 2.0, 0.85

ADX_MINS = [None, 15, 20, 25, 30]


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
    return f"거래{n:>3}건 승률{win_rate:5.1f}% PF{pf:5.2f} 수익률{total_return:+8.2f}% MDD{mdd:5.1f}%"


if __name__ == "__main__":
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT", "ADAUSDT", "NEARUSDT"]

    results = {a: [] for a in ADX_MINS}

    bcl.SQUEEZE_ENTER_MULT = 0.5
    bcl.BREAKOUT_MULT = 1.5

    for sym in coins:
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 1시간봉 데이터 수집 중...", flush=True)
        candles = bcl.fetch_klines(sym, "60", DAYS)
        print(f"캔들 {len(candles)}개 수집 완료", flush=True)

        print(f"\n--- {sym} ADX 레짐필터 스윕 (sq=0.5 bo=1.5, 1h, profit_lock 2.0/0.85) ---")
        for a in ADX_MINS:
            trades, seed = bcl.run_backtest(candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR, adx_min=a)
            total_return = (seed - bcl.SEED) / bcl.SEED * 100
            results[a].append(total_return)
            label = f"adx_min={a}" if a is not None else "adx없음(현재라이브)"
            print(f"  {label}: {quick_stats(trades, seed)}", flush=True)

    print(f"\n\n=== 코인 평균 수익률 ===")
    for a in ADX_MINS:
        avg = sum(results[a]) / len(results[a]) if results[a] else 0
        label = f"adx_min={a}" if a is not None else "adx없음(현재라이브)"
        print(f"  {label}: 평균 {avg:+.2f}%  (개별: {['%+.2f%%' % r for r in results[a]]})")

    print("\n\n=== ADX FILTER SWEEP COMPLETE ===", flush=True)
