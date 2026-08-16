"""
2026-08-14: run_backtest()의 "총수익률/최종시드"는 매 거래마다 그 시점까지 불어난
시드의 75%를 10배 레버리지로 베팅하는 복리 구조라, 거래가 수백 건 쌓이면 숫자가
기하급수적으로 폭발해서(조 단위 등) 실제 체감 가능한 수익률로 보기 어려움.

여기서는 "매 거래마다 항상 최초 시드(SEED) 기준으로 고정된 명목가치(75% x 10배)로
베팅했다면" 이라는 가정으로 복리 없이 단순 합산한 수익률을 계산 - 사용자가 실제
체감할 수 있는 숫자에 가깝게 보기 위함. (실전에서는 지갑 재분배 등으로 완전한
고정 배팅도 완전한 복리도 아닌 중간 어딘가지만, 최소한 극단적 복리 착시는 제거됨)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

bcl.SQUEEZE_ENTER_MULT = 0.7
bcl.BREAKOUT_MULT = 1.6

INTERVAL = "15"
DAYS = 730
COINS = ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]

FIXED_NOTIONAL = bcl.SEED * bcl.ENTRY_PERCENT * bcl.LEVERAGE  # 항상 최초시드 기준 고정 배팅


def fixed_notional_stats(trades):
    """trades[i]['pct']는 수수료 반영 전 순수 가격변동률(%). 고정 명목가치로 재계산."""
    total_pnl = 0.0
    wins = 0
    for t in trades:
        raw_frac = t["pct"] / 100
        pnl = FIXED_NOTIONAL * raw_frac - FIXED_NOTIONAL * bcl.FEE_RATE * 2
        total_pnl += pnl
        if pnl > 0:
            wins += 1
    n = len(trades)
    win_rate = wins / n * 100 if n else 0
    total_return_pct = total_pnl / bcl.SEED * 100  # 최초 시드 대비 총수익률(복리 아님, 단순합산)
    return n, win_rate, total_pnl, total_return_pct


def main():
    base_all = []
    new_all = []

    for sym in COINS:
        candles = bcl.fetch_klines(sym, INTERVAL, DAYS)

        trades_base, _ = bcl.run_backtest(candles, use_hma_regime_filter=True)
        trades_new, _ = bcl.run_backtest(candles, use_hma_direction_only=True)
        base_all.extend(trades_base)
        new_all.extend(trades_new)

        n_b, wr_b, pnl_b, ret_b = fixed_notional_stats(trades_base)
        n_n, wr_n, pnl_n, ret_n = fixed_notional_stats(trades_new)
        print(f"\n[{sym}]")
        print(f"  기존: {n_b}건 승률{wr_b:.1f}% 고정배팅합산손익 ${pnl_b:,.0f} 수익률(730일, 비복리) {ret_b:+.1f}%")
        print(f"  신규: {n_n}건 승률{wr_n:.1f}% 고정배팅합산손익 ${pnl_n:,.0f} 수익률(730일, 비복리) {ret_n:+.1f}%")

    print(f"\n{'='*60}\n4코인 합산 (고정배팅/비복리, 코인당 시드 $1000씩 별도 가정)\n{'='*60}")
    n_b, wr_b, pnl_b, ret_b = fixed_notional_stats(base_all)
    n_n, wr_n, pnl_n, ret_n = fixed_notional_stats(new_all)
    print(f"기존: {n_b}건  승률 {wr_b:.1f}%  합산손익 ${pnl_b:,.0f}  코인당평균수익률 {ret_b/4:+.1f}%")
    print(f"신규: {n_n}건  승률 {wr_n:.1f}%  합산손익 ${pnl_n:,.0f}  코인당평균수익률 {ret_n/4:+.1f}%")

    # 참고: 연환산(730일=약2년 기준)
    print(f"\n참고 - 연환산(단순 절반, 복리 아님):")
    print(f"기존: 연 {ret_b/4/2:+.1f}%   신규: 연 {ret_n/4/2:+.1f}%")


if __name__ == "__main__":
    main()
