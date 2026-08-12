"""2026-08-12 실험: 15분봉 sq/bo 스윕에서 나온 극단적 결과(sq=0.7/bo=1.6 등)가
과최적화(같은 데이터로 고르고 같은 데이터로 평가)인지 확인하기 위한 워크포워드(out-of-sample) 검증.

방법:
  1. 730일치 15분봉 데이터를 코인당 1회 수집 (앞 365일=훈련구간 A, 뒤 365일=검증구간 B).
  2. 전체 730일 데이터로 딱 한 번 백테스트를 돌려 거래 리스트를 얻는다
     (이러면 구간 B 초반 거래도 HMA600 등 워밍업이 구간 A 데이터로 정상적으로 채워짐).
  3. 거래를 entry_ts 기준으로 A/B 두 구간으로 나눈다.
  4. 각 구간을 "그 구간 시작 시점에 $1,000로 새로 시작했다면"을 가정해 거래별 pct(%)를 이용해
     복리를 독립적으로 재계산한다 (구간 B 실적이 구간 A의 복리 결과에 얹혀서 부풀려지는 걸 방지).
  5. 스윕에서 나온 후보 파라미터(보수적~공격적)들에 대해 A(훈련) 성과와 B(검증) 성과를 나란히 비교.
     A에서 좋았던 파라미터가 B에서도 비슷하게 좋아야 "진짜 엣지"에 가깝고, B에서 무너지면
     A 결과는 과최적화(그 시기에만 맞았던 우연)로 봐야 한다.

사용법: python backtest_15m_walkforward.py [DAYS_TOTAL]
"""
import sys

import backtest_current_live as bcl

DAYS_TOTAL = int(sys.argv[1]) if len(sys.argv) > 1 else 730
COINS = ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]
PLT, PLR = 0.5, 0.85

# 스윕 결과에서 고른 대표 후보 (보수적 -> 공격적)
COMBOS = [
    (0.4, 1.3),   # 스윕 최하위(가장 보수적)
    (0.5, 1.3),
    (0.5, 1.6),
    (0.6, 1.6),
    (0.7, 1.6),   # 스윕 1위(가장 공격적/의심)
    (0.7, 2.0),   # 스윕 2위
]


def recompute_fresh(trades_subset):
    """구간 시작 시점에 SEED로 새로 시작했다고 가정하고 복리 재계산."""
    seed = bcl.SEED
    recon = []
    for t in trades_subset:
        notional = seed * bcl.ENTRY_PERCENT * bcl.LEVERAGE
        raw_pct = t["pct"] / 100
        pnl = notional * raw_pct - notional * bcl.FEE_RATE * 2
        seed += pnl
        recon.append({**t, "profit": pnl})
    return recon, seed


def stats(trades, final_seed):
    n = len(trades)
    if n == 0:
        return dict(n=0, win_rate=0.0, pf=0.0, ret=0.0, mdd=0.0)
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
    print(f"15분봉 {DAYS_TOTAL}일치 데이터 수집 중 (코인 {len(COINS)}개)...", flush=True)
    candle_cache = {}
    split_ts = {}
    for sym in COINS:
        candles = bcl.fetch_klines(sym, "15", DAYS_TOTAL)
        candle_cache[sym] = candles
        split_ts[sym] = candles[0]["ts"] + (candles[-1]["ts"] - candles[0]["ts"]) // 2
        print(f"  {sym}: {len(candles)}개 캔들 수집 완료", flush=True)

    all_results = []  # (sq, bo, sym, statsA, statsB)
    for sq, bo in COMBOS:
        bcl.SQUEEZE_ENTER_MULT = sq
        bcl.BREAKOUT_MULT = bo
        print(f"\n{'='*70}\n[sq={sq} bo={bo}]", flush=True)
        for sym in COINS:
            candles = candle_cache[sym]
            trades, _ = bcl.run_backtest(candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
                                          use_hma_regime_filter=True)
            trades_a = [t for t in trades if t["entry_ts"] < split_ts[sym]]
            trades_b = [t for t in trades if t["entry_ts"] >= split_ts[sym]]
            recon_a, seed_a = recompute_fresh(trades_a)
            recon_b, seed_b = recompute_fresh(trades_b)
            st_a = stats(recon_a, seed_a)
            st_b = stats(recon_b, seed_b)
            all_results.append((sq, bo, sym, st_a, st_b))
            print(f"  {sym}:")
            print(f"    A(훈련,앞365일): 거래{st_a['n']:>3}건 승률{st_a['win_rate']:5.1f}% PF{st_a['pf']:5.2f} "
                  f"수익률{st_a['ret']:+9.2f}% MDD{st_a['mdd']:5.1f}%")
            print(f"    B(검증,뒤365일): 거래{st_b['n']:>3}건 승률{st_b['win_rate']:5.1f}% PF{st_b['pf']:5.2f} "
                  f"수익률{st_b['ret']:+9.2f}% MDD{st_b['mdd']:5.1f}%")
            flag = ""
            if st_a["ret"] > 100 and st_b["ret"] < 0:
                flag = "  <== 훈련구간 좋았는데 검증구간 마이너스! 과최적화 의심"
            elif st_a["pf"] > 1 and st_b["pf"] < 1:
                flag = "  <== 검증구간 PF<1 (기대값 마이너스)"
            if flag:
                print(f"   {flag}", flush=True)

    print(f"\n\n{'#'*70}\n=== 파라미터별 A(훈련)/B(검증) 평균 비교 (4코인 평균) ===")
    print(f"{'sq':>4} {'bo':>4} {'A평균수익률':>12} {'A평균PF':>8} {'B평균수익률':>12} {'B평균PF':>8} {'B평균MDD':>9}")
    for sq, bo in COMBOS:
        rows = [r for r in all_results if r[0] == sq and r[1] == bo]
        a_ret = sum(r[3]["ret"] for r in rows) / len(rows)
        a_pf = sum(r[3]["pf"] for r in rows if r[3]["pf"] != float("inf")) / max(1, len([r for r in rows if r[3]["pf"] != float("inf")]))
        b_ret = sum(r[4]["ret"] for r in rows) / len(rows)
        b_pf = sum(r[4]["pf"] for r in rows if r[4]["pf"] != float("inf")) / max(1, len([r for r in rows if r[4]["pf"] != float("inf")]))
        b_mdd = sum(r[4]["mdd"] for r in rows) / len(rows)
        print(f"{sq:>4} {bo:>4} {a_ret:>11.2f}% {a_pf:>8.2f} {b_ret:>11.2f}% {b_pf:>8.2f} {b_mdd:>8.1f}%")

    print("\n\n=== 15M WALK-FORWARD VALIDATION COMPLETE ===", flush=True)
