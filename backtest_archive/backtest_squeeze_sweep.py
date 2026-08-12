"""2026-08-11 실험: 스퀴즈/브레이크아웃 감지 임계값(SQUEEZE_ENTER_MULT, BREAKOUT_MULT) 스윕.

현재 라이브 값: SQUEEZE_ENTER_MULT=0.5(폭이 평균의 50% 이하로 눌리면 스퀴즈 진입),
BREAKOUT_MULT=1.5(스퀴즈 최저폭의 1.5배 이상 벌어지면 브레이크아웃).

1시간봉 신호가 너무 적다는 문제(400일에 코인당 50~65건) 해결 후보로, 이 두 임계값을
완화(SQUEEZE_ENTER_MULT 상향/BREAKOUT_MULT 하향)했을 때 신호가 늘면서도 성과가
유지/개선되는지, 아니면 질 나쁜 신호만 늘어 성과가 나빠지는지 검증.

run_backtest()가 이 두 값을 파라미터로 안 받고 모듈 전역변수를 직접 참조하므로
(backtest_no_cooldown.py와 동일 패턴), 모듈을 import해서 몽키패치.

profit_lock(2.0/0.85)은 정확히 반영, 1시간봉 고정, 청산로직은 기존(HMA200 Break) 그대로.

사용법: python backtest_squeeze_sweep.py [SYMBOL] [DAYS] [SYMBOL2 ...]
"""
import sys
from datetime import datetime

import backtest_current_live as bcl

DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else bcl.DAYS
PLT, PLR = 2.0, 0.85

SQUEEZE_ENTER_MULTS = [0.4, 0.5, 0.6, 0.7]
BREAKOUT_MULTS = [1.2, 1.5, 1.8, 2.0]


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

    for sym in coins:
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 1시간봉 데이터 수집 중...", flush=True)
        candles = bcl.fetch_klines(sym, "60", DAYS)
        print(f"캔들 {len(candles)}개 수집 완료", flush=True)

        print(f"\n--- {sym} SQUEEZE_ENTER_MULT x BREAKOUT_MULT 스윕 (1h, profit_lock 2.0/0.85) ---")
        for sq in SQUEEZE_ENTER_MULTS:
            for bo in BREAKOUT_MULTS:
                bcl.SQUEEZE_ENTER_MULT = sq
                bcl.BREAKOUT_MULT = bo
                trades, seed = bcl.run_backtest(candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR)
                tag = " <= 현재라이브" if (sq == 0.5 and bo == 1.5) else ""
                print(f"  sq={sq} bo={bo}: {quick_stats(trades, seed)}{tag}", flush=True)

    print("\n\n=== SQUEEZE SWEEP COMPLETE ===", flush=True)
