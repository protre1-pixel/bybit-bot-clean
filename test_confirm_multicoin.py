# -*- coding: utf-8 -*-
# 2026-08-07: "확인캔들 ON + 돌파배수 1.5(기존) + BB30 + SL=min(avg_width,3%)" 조합이
# XRP 단독으로는 -23.43% -> +1.16%로 개선됐는데, 이게 XRP에만 우연히 맞은 건지
# 다른 코인에서도 통하는지 검증하기 위한 멀티코인 백테스트.
import sys

# test_current_live_xrp 모듈은 import 시점의 sys.argv로 CONFIRM/BREAKOUT_MULT/BB20 등
# 전역 상수를 확정하므로, import 전에 원하는 조합을 argv로 세팅해둔다.
sys.argv = ["test_current_live_xrp.py", "XRPUSDT", "120", "--confirm"]
import test_current_live_xrp as tcl

SYMBOLS = ["XRPUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"]
DAYS = 120

print(f"조건: BB밴드길이={tcl.WIDTH_LOOKBACK}, 돌파배수={tcl.BREAKOUT_MULT}, 확인캔들={tcl.CONFIRM}, "
      f"SL=min(avg_width,{tcl.SL_PERCENT*100:.0f}%)")
print()

results = []
for symbol in SYMBOLS:
    print(f"[{symbol}] {DAYS}일치 데이터 수집 중...")
    candles = tcl.bt.fetch_klines(symbol, tcl.INTERVAL, DAYS)
    trades, final_seed = tcl.run(candles)

    n = len(trades)
    if n == 0:
        print(f"  {symbol}: 거래 없음")
        print()
        continue

    wins = [t for t in trades if t["profit"] > 0]
    wr = len(wins) / n * 100
    gw = sum(t["profit"] for t in wins)
    gl = -sum(t["profit"] for t in trades if t["profit"] <= 0)
    pf = gw / gl if gl > 0 else float("inf")
    ret = (final_seed - tcl.SEED) / tcl.SEED * 100
    curve = [tcl.SEED]
    s = tcl.SEED
    for t in trades:
        s += t["profit"]
        curve.append(s)
    peak = curve[0]
    mdd = 0
    for v in curve:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak * 100)
    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    reason_str = ", ".join(f"{k}:{v}" for k, v in sorted(reasons.items()))

    print(f"  {symbol:10s} 거래{n:3d} 승률{wr:5.1f}% PF{pf:5.2f} 수익률{ret:+7.2f}% "
          f"최종시드${final_seed:8.2f} MDD{mdd:5.1f}%  [{reason_str}]")
    print()
    results.append((symbol, n, wr, pf, ret, final_seed, mdd))

print("=== 요약 ===")
positive = sum(1 for r in results if r[4] > 0)
avg_ret = sum(r[4] for r in results) / len(results) if results else 0
avg_pf = sum(r[3] if r[3] != float("inf") else 5.0 for r in results) / len(results) if results else 0
print(f"플러스 코인: {positive}/{len(results)}   평균수익률: {avg_ret:+.2f}%   평균PF: {avg_pf:.2f}")
