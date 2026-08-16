"""
2026-08-16: "전략#2"(use_hma_direction_only=True, profit_lock 0.5/0.85 - 현재 라이브 배포 설정)의
1년 백테스트 결과를 월별로 쪼개서, 전체 합산 성과가 특정 달에 몰빵된 결과인지 아니면 꾸준한지 확인.

스코프: XRP만, 15분봉, 365일치, sq=0.7/bo=1.6(라이브 동일), profit_lock(0.5/0.85) 유지,
use_hma_direction_only=True 단독 (다른 조합 없음 - 어제 4종 비교에서 채택된 설정 그대로).
"""
import sys
import os
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

SYMBOL = "XRPUSDT"
INTERVAL = "15"
DAYS = 365

bcl.SQUEEZE_ENTER_MULT = 0.7
bcl.BREAKOUT_MULT = 1.6
PLT, PLR = 0.5, 0.85

candles = bcl.fetch_klines(SYMBOL, INTERVAL, DAYS)

trades, seed_end = bcl.run_backtest(
    candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
    use_hma_direction_only=True)

print(f"\n총 거래수: {len(trades)}건")
if not trades:
    print("거래 없음 - 종료")
    sys.exit(0)

buckets = defaultdict(list)
for t in trades:
    dt = datetime.fromtimestamp(t["entry_ts"] / 1000)
    key = (dt.year, dt.month)
    buckets[key].append(t)

months = sorted(buckets.keys())

print("\n| 월 | 거래수 | 익절 | 손절 | 승률 | PF | 거래당평균% | 비복리합산% |")
print("|---|---|---|---|---|---|---|---|")

cum_sum_pct = 0.0
total_wins = 0
total_losses = 0
for (y, m) in months:
    mt = buckets[(y, m)]
    wins = [t for t in mt if t["profit"] > 0]
    losses = [t for t in mt if t["profit"] <= 0]
    total_wins += len(wins)
    total_losses += len(losses)
    win_rate = len(wins) / len(mt) * 100
    gross_win = sum(t["profit"] for t in wins)
    gross_loss = -sum(t["profit"] for t in losses)
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    avg_pct = sum(t["pct"] for t in mt) / len(mt)
    sum_pct = sum(t["pct"] for t in mt)
    cum_sum_pct += sum_pct
    pf_str = f"{pf:.2f}" if pf != float("inf") else "inf"
    print(f"| {y}-{m:02d} | {len(mt)} | {len(wins)} | {len(losses)} | {win_rate:.1f}% | {pf_str} | {avg_pct:+.3f}% | {sum_pct:+.1f}% |")

print(f"\n합계: 익절 {total_wins}건 / 손절 {total_losses}건 (총 {total_wins+total_losses}건)")

print(f"\n누적 비복리 합산%: {cum_sum_pct:+.1f}%  (전체 {len(trades)}건 기준)")
print("\n=== REGIME DIRECTION MONTHLY XRP 1Y TEST COMPLETE ===", flush=True)
