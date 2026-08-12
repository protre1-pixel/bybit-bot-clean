"""2026-08-11 실험: sq=1.0/bo=1.5에서 ETH가 +761.03%(400일)라는 극단적 수익률을 보였는데,
이게 "전략이 실제로 좋아져서"인지 "소수의 초대형 트레이드에 우연히 몰빵되어서"인지 확인.

거래 리스트를 개별로 까서 상위 N개 트레이드가 전체 수익에서 차지하는 비중, 최대 단일
트레이드 수익, 승패 분포(테일 리스크)를 직접 본다.

사용법: python backtest_inspect_eth_sq10.py
"""
from datetime import datetime

import backtest_current_live as bcl

DAYS = 400
PLT, PLR = 2.0, 0.85

candles = bcl.fetch_klines("ETHUSDT", "60", DAYS)
print(f"캔들 {len(candles)}개 수집 완료", flush=True)

bcl.SQUEEZE_ENTER_MULT = 1.0
bcl.BREAKOUT_MULT = 1.5

trades, seed = bcl.run_backtest(candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR)

n = len(trades)
total_profit = sum(t["profit"] for t in trades)
print(f"\n총 거래 {n}건, 총손익 ${total_profit:.2f}, 최종시드 ${seed:.2f} (수익률 {(seed-bcl.SEED)/bcl.SEED*100:+.2f}%)")

sorted_trades = sorted(trades, key=lambda t: t["profit"], reverse=True)
print("\n=== 상위 10개 트레이드 ===")
cum = 0
for i, t in enumerate(sorted_trades[:10], 1):
    cum += t["profit"]
    pct_of_total = cum / total_profit * 100 if total_profit != 0 else 0
    entry_dt = datetime.fromtimestamp(t["entry_ts"] / 1000).strftime("%Y-%m-%d")
    hold_h = t.get("hold_h", 0)
    print(f"  {i:>2}. profit=${t['profit']:>9.2f}  pct={t.get('pct',0):>6.1f}%  reason={t.get('reason','?'):<20} "
          f"entry={entry_dt}  hold={hold_h:>5.1f}h  누적비중={pct_of_total:5.1f}%")

print("\n=== 하위 5개 트레이드(최대 손실) ===")
for i, t in enumerate(sorted_trades[-5:], 1):
    print(f"  {i:>2}. profit=${t['profit']:>9.2f}  reason={t.get('reason','?')}")

top3 = sum(t["profit"] for t in sorted_trades[:3])
top5 = sum(t["profit"] for t in sorted_trades[:5])
top10 = sum(t["profit"] for t in sorted_trades[:10])
print(f"\n상위 3건이 총손익의 {top3/total_profit*100:.1f}%")
print(f"상위 5건이 총손익의 {top5/total_profit*100:.1f}%")
print(f"상위10건이 총손익의 {top10/total_profit*100:.1f}%")

wins = [t for t in trades if t["profit"] > 0]
losses = [t for t in trades if t["profit"] <= 0]
print(f"\n승={len(wins)}건 평균수익=${(sum(t['profit'] for t in wins)/len(wins)) if wins else 0:.2f}")
print(f"패={len(losses)}건 평균손실=${(sum(t['profit'] for t in losses)/len(losses)) if losses else 0:.2f}")
