"""2026-08-12: 코인별 청산 사유(익절/손절/트레일링/추세반전) 분포와 %pct 통계
(최대/평균)를 뽑아보기 위한 스크립트. 사용자 질문: "각 코인마다 익절/손절 구분해줄수
있어? 그리고 최대 %는 몇프로야? 평균은 몇%야?"

현재 라이브 파라미터(sq=0.7, bo=1.6, profit_lock 0.5%/0.85, HMA200/600 regime filter,
15분봉) 그대로, 코인별 730일 데이터로 백테스트해서 거래별 pct(레버리지 적용 전, 가격
변동률 자체)를 이용해 통계를 낸다.

사용법: python backtest_reason_breakdown.py [DAYS]
"""
import sys

import backtest_current_live as bcl

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 730
COINS = ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]
PLT, PLR = 0.5, 0.85

bcl.SQUEEZE_ENTER_MULT = 0.7
bcl.BREAKOUT_MULT = 1.6


def analyze(trades):
    n = len(trades)
    wins = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] <= 0]
    by_reason = {}
    for t in trades:
        by_reason.setdefault(t["reason"], []).append(t)
    pcts = [t["pct"] for t in trades]
    win_pcts = [t["pct"] for t in wins]
    loss_pcts = [t["pct"] for t in losses]
    return dict(
        n=n, wins=len(wins), losses=len(losses),
        win_rate=len(wins) / n * 100 if n else 0,
        by_reason=by_reason,
        max_pct=max(pcts) if pcts else 0,
        min_pct=min(pcts) if pcts else 0,
        avg_pct=sum(pcts) / n if n else 0,
        avg_win_pct=sum(win_pcts) / len(win_pcts) if win_pcts else 0,
        avg_loss_pct=sum(loss_pcts) / len(loss_pcts) if loss_pcts else 0,
        max_win_pct=max(win_pcts) if win_pcts else 0,
        max_loss_pct=min(loss_pcts) if loss_pcts else 0,
    )


if __name__ == "__main__":
    print(f"15분봉 {DAYS}일치 데이터 수집 및 백테스트 중 (코인 {len(COINS)}개, sq=0.7 bo=1.6)...\n", flush=True)

    all_trades_by_coin = {}
    for sym in COINS:
        candles = bcl.fetch_klines(sym, "15", DAYS)
        trades, _ = bcl.run_backtest(candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
                                      use_hma_regime_filter=True)
        all_trades_by_coin[sym] = trades
        print(f"  {sym}: 캔들 {len(candles)}개, 거래 {len(trades)}건", flush=True)

    print(f"\n{'='*78}")
    for sym in COINS:
        trades = all_trades_by_coin[sym]
        st = analyze(trades)
        print(f"\n[{sym}] 총 거래 {st['n']}건  승 {st['wins']}건 / 패 {st['losses']}건  승률 {st['win_rate']:.1f}%")
        print(f"  청산 사유별 분포:")
        for reason, lst in sorted(st["by_reason"].items(), key=lambda x: -len(x[1])):
            r_wins = [t for t in lst if t["profit"] > 0]
            r_win_rate = len(r_wins) / len(lst) * 100 if lst else 0
            r_avg_pct = sum(t["pct"] for t in lst) / len(lst) if lst else 0
            print(f"    {reason:<20}: {len(lst):>4}건 ({len(lst)/st['n']*100:5.1f}%)  "
                  f"그 중 승 {r_win_rate:5.1f}%  평균pct {r_avg_pct:+6.2f}%")
        print(f"  거래당 %(가격변동률, 레버리지 적용 전) 기준:")
        print(f"    전체 평균: {st['avg_pct']:+6.2f}%   최대(최고익): {st['max_pct']:+6.2f}%   최소(최대손실): {st['min_pct']:+6.2f}%")
        print(f"    승 거래 평균: {st['avg_win_pct']:+6.2f}%  (최고 {st['max_win_pct']:+6.2f}%)")
        print(f"    패 거래 평균: {st['avg_loss_pct']:+6.2f}%  (최악 {st['max_loss_pct']:+6.2f}%)")

    print(f"\n\n{'#'*78}\n=== 4코인 합산 요약 ===")
    all_trades = [t for sym in COINS for t in all_trades_by_coin[sym]]
    st = analyze(all_trades)
    print(f"총 거래 {st['n']}건  승 {st['wins']}건 / 패 {st['losses']}건  승률 {st['win_rate']:.1f}%")
    for reason, lst in sorted(st["by_reason"].items(), key=lambda x: -len(x[1])):
        r_wins = [t for t in lst if t["profit"] > 0]
        r_win_rate = len(r_wins) / len(lst) * 100 if lst else 0
        r_avg_pct = sum(t["pct"] for t in lst) / len(lst) if lst else 0
        print(f"  {reason:<20}: {len(lst):>4}건 ({len(lst)/st['n']*100:5.1f}%)  "
              f"그 중 승 {r_win_rate:5.1f}%  평균pct {r_avg_pct:+6.2f}%")
    print(f"전체 평균pct: {st['avg_pct']:+6.2f}%   최대: {st['max_pct']:+6.2f}%   최소: {st['min_pct']:+6.2f}%")

    print("\n\n=== REASON BREAKDOWN COMPLETE ===", flush=True)
