"""2026-08-12 실험: 15분봉 전용 SQUEEZE_ENTER_MULT x BREAKOUT_MULT 재최적화.

1시간봉용으로 튜닝된 sq=0.5/bo=1.5를 그대로 15분봉에 쓰면 기존 필터가 붕괴하고(-80% 평균),
신규 HMA200/600 정배열 필터도 그 붕괴한 기반 위에서 상대적으로 좋아 보이는 것뿐이라
공정한 비교가 아니었음. 이 스크립트는 15분봉 데이터로 sq/bo 그리드를 스윕하면서
신규 필터(use_hma_regime_filter=True)를 적용해 15분봉에 맞는 파라미터를 찾는다.

profit_lock(trigger=0.5%, ratio=0.85)은 현재 라이브 값 고정. 각 코인 캔들은 1회만
fetch해서 재사용(속도 최적화 - run_backtest 1회가 15분봉 365일 데이터에서 ~40초 소요).

사용법: python backtest_15m_regime_sweep.py [DAYS]
"""
import sys

import backtest_current_live as bcl

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else bcl.DAYS
COINS = ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]

SQUEEZE_ENTER_MULTS = [0.4, 0.5, 0.6, 0.7]
BREAKOUT_MULTS = [1.3, 1.6, 2.0]
PLT, PLR = 0.5, 0.85


def stats(trades, final_seed):
    n = len(trades)
    if n == 0:
        return dict(n=0, win_rate=0.0, pf=0.0, ret=-100.0, mdd=0.0)
    wins = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] <= 0]
    win_rate = len(wins) / n * 100
    gross_win = sum(t["profit"] for t in wins)
    gross_loss = -sum(t["profit"] for t in losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    ret = (final_seed - bcl.SEED) / bcl.SEED * 100
    curve = [bcl.SEED]
    s = bcl.SEED
    for t in trades:
        s += t["profit"]
        curve.append(s)
    peak = curve[0]
    mdd = 0.0
    for v in curve:
        peak = max(peak, v)
        dd = (peak - v) / peak * 100 if peak > 0 else 0
        mdd = max(mdd, dd)
    return dict(n=n, win_rate=win_rate, pf=pf, ret=ret, mdd=mdd)


if __name__ == "__main__":
    print(f"15분봉 {DAYS}일치 데이터 수집 중 (코인 {len(COINS)}개)...", flush=True)
    candle_cache = {}
    for sym in COINS:
        candle_cache[sym] = bcl.fetch_klines(sym, "15", DAYS)
        print(f"  {sym}: {len(candle_cache[sym])}개 캔들 수집 완료", flush=True)

    combos = [(sq, bo) for sq in SQUEEZE_ENTER_MULTS for bo in BREAKOUT_MULTS]
    total = len(combos)
    results = []
    done = 0
    for sq, bo in combos:
        bcl.SQUEEZE_ENTER_MULT = sq
        bcl.BREAKOUT_MULT = bo
        per_coin = {}
        for sym in COINS:
            trades, seed = bcl.run_backtest(candle_cache[sym], profit_lock_trigger_pct=PLT,
                                             profit_lock_ratio=PLR, use_hma_regime_filter=True)
            per_coin[sym] = stats(trades, seed)
        avg_ret = sum(per_coin[s]["ret"] for s in COINS) / len(COINS)
        avg_mdd = sum(per_coin[s]["mdd"] for s in COINS) / len(COINS)
        avg_n = sum(per_coin[s]["n"] for s in COINS) / len(COINS)
        min_ret = min(per_coin[s]["ret"] for s in COINS)
        results.append((sq, bo, avg_ret, avg_mdd, avg_n, min_ret, per_coin))
        done += 1
        print(f"  [{done}/{total}] sq={sq} bo={bo}: 평균수익률{avg_ret:+9.2f}% 평균MDD{avg_mdd:5.1f}% "
              f"평균거래수{avg_n:5.1f} 최소수익률{min_ret:+9.2f}%", flush=True)
        for sym in COINS:
            st = per_coin[sym]
            print(f"        {sym}: 거래{st['n']:>3}건 승률{st['win_rate']:5.1f}% PF{st['pf']:5.2f} "
                  f"수익률{st['ret']:+9.2f}% MDD{st['mdd']:5.1f}%", flush=True)

    results.sort(key=lambda r: r[2], reverse=True)
    print("\n\n=== TOP (평균 수익률 기준 정렬) ===")
    print(f"{'sq':>4} {'bo':>4} {'평균수익률':>12} {'평균MDD':>8} {'평균거래수':>8} {'최소수익률':>10}")
    for sq, bo, avg_ret, avg_mdd, avg_n, min_ret, per_coin in results:
        print(f"{sq:>4} {bo:>4} {avg_ret:>11.2f}% {avg_mdd:>7.1f}% {avg_n:>8.1f} {min_ret:>9.2f}%")

    results.sort(key=lambda r: r[5], reverse=True)
    print("\n\n=== TOP (최소(가장 나쁜 코인) 수익률 기준 정렬 - 견고성) ===")
    print(f"{'sq':>4} {'bo':>4} {'평균수익률':>12} {'평균MDD':>8} {'평균거래수':>8} {'최소수익률':>10}")
    for sq, bo, avg_ret, avg_mdd, avg_n, min_ret, per_coin in results:
        print(f"{sq:>4} {bo:>4} {avg_ret:>11.2f}% {avg_mdd:>7.1f}% {avg_n:>8.1f} {min_ret:>9.2f}%")

    print("\n\n=== 15M REGIME SWEEP COMPLETE ===", flush=True)
