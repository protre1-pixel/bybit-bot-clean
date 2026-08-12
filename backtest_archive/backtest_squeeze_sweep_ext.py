"""2026-08-11 실험 확장: backtest_squeeze_sweep.py에서 sq=0.6/0.7이 평균 수익률을
끌어올리는 추세를 보여서, bo=1.5(현재 라이브 값) 고정하고 sq를 0.8~1.0까지 더 밀어서
그 추세가 계속되는지, 어디서 꺾이는지 확인.

주의: SQUEEZE_ENTER_MULT는 "현재 폭 < 평균 폭 * SQUEEZE_ENTER_MULT"일 때 스퀴즈 진입으로
판정하는 임계값이라, 1.0에 가까워질수록 "평균보다 좁기만 하면 스퀴즈"가 되어 버려서
원래 의도(눌림→돌파 패턴)에서 점점 멀어짐 - 이 sq 값들에서 신호 품질이 실제로 좋아지는건지
아니면 그냥 진입 빈도가 늘면서 우연히 잘 맞은 코인이 평균을 끌어올리는 건지 결과 보면서 판단.

사용법: python backtest_squeeze_sweep_ext.py [SYMBOL] [DAYS] [SYMBOL2 ...]
"""
import sys
from datetime import datetime

import backtest_current_live as bcl

DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else bcl.DAYS
PLT, PLR = 2.0, 0.85

SQUEEZE_ENTER_MULTS = [0.5, 0.6, 0.7]
BO = 1.5  # 현재 라이브 값 고정


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
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]

    results = {sq: [] for sq in SQUEEZE_ENTER_MULTS}

    for sym in coins:
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 1시간봉 데이터 수집 중...", flush=True)
        candles = bcl.fetch_klines(sym, "60", DAYS)
        print(f"캔들 {len(candles)}개 수집 완료", flush=True)

        print(f"\n--- {sym} SQUEEZE_ENTER_MULT 확장 스윕 (bo={BO} 고정, 1h, profit_lock 2.0/0.85) ---")
        bcl.BREAKOUT_MULT = BO
        for sq in SQUEEZE_ENTER_MULTS:
            bcl.SQUEEZE_ENTER_MULT = sq
            trades, seed = bcl.run_backtest(candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR)
            total_return = (seed - bcl.SEED) / bcl.SEED * 100
            results[sq].append(total_return)
            print(f"  sq={sq} bo={BO}: {quick_stats(trades, seed)}", flush=True)

    print(f"\n\n=== 코인 평균 수익률 (bo={BO} 고정) ===")
    for sq in SQUEEZE_ENTER_MULTS:
        avg = sum(results[sq]) / len(results[sq]) if results[sq] else 0
        print(f"  sq={sq}: 평균 {avg:+.2f}%  (개별: {['%+.2f%%' % r for r in results[sq]]})")

    print("\n\n=== SQUEEZE SWEEP EXT COMPLETE ===", flush=True)
