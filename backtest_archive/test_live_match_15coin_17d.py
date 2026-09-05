"""
2026-09-05(39차): 백테스트 엔진이 실제 라이브(bot1, paper mode)와 얼마나 일치하는지 직접
검증하기 위한 테스트. bot1이 8/19 대장주 화이트리스트 배포 이후 지금까지(17일간) 실제로
거래한 코인 15종 전부를, 같은 기간(2026-08-19~2026-09-05) 15분봉으로 받아서 현재 라이브와
동일한 파라미터로 run_backtest() 실행 후 실제 bot1 거래 기록(trades.json, 610건)과 대조.

LIVE_KWARGS/상수는 현재 trading_service.py에서 직접 확인한 값과 일치:
SQUEEZE_ENTER_MULT=0.85, BREAKOUT_MULTIPLIER=1.3, LEVERAGE=10, entry_sl_cap_pct=None(SL 3.5%
기본값 그대로), profit_lock_trigger_pct=0.5/ratio=0.8(8/21 배포분), stall_exit_candles=8/
min_peak=0.5%/sl=0.4%, use_hma_direction_only, use_price_alignment_filter, use_fast_breakout
(lookback=2), use_regime_exit. REENTRY_COOLDOWN_MS은 1시간(3600*1000)으로 패치(8/19 라이브 변경분).
홀드윈도우는 8/19에 완전 삭제된 상태라 run_backtest() 자체에 애초에 그런 로직이 없음(그대로 사용).

스코프: bot1이 실제 거래한 15종(ADA/ATOM/AVAX/BCH/BNB/BTC/DOGE/DOT/ETH/LINK/LTC/NEAR/SOL/TRX/XRP),
15분봉, 17일(2026-08-19~2026-09-05).

실제 bot1 결과(trades.json 610건, SSH로 조회):
전체 n=610 승률70.8% PF1.12 합산수익 +$998.58
ADA n=51 승률76.5% 수익-188.06 / ATOM n=30 승률60.0% 수익-70.21 / AVAX n=34 승률73.5% 수익+288.10
BCH n=62 승률75.8% 수익+411.20 / BNB n=42 승률71.4% 수익+235.09 / BTC n=39 승률56.4% 수익-92.10
DOGE n=42 승률59.5% 수익-531.76 / DOT n=53 승률79.2% 수익+296.42 / ETH n=33 승률66.7% 수익+221.03
LINK n=49 승률69.4% 수익+114.14 / LTC n=36 승률72.2% 수익+248.52 / NEAR n=29 승률75.9% 수익+89.44
SOL n=38 승률71.1% 수익-125.97 / TRX n=29 승률58.6% 수익-90.71 / XRP n=43 승률83.7% 수익+193.45
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

COINS = ["ADA", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETH",
         "LINK", "LTC", "NEAR", "SOL", "TRX", "XRP"]
INTERVAL = "15"
# 2026-09-05: 최초 시도(DAYS=17로 딱 맞춰 fetch)했더니 백테스트 거래수가 128건으로
# 실제 bot1(610건)의 1/5도 안 됨 - 원인은 run_backtest()의 워밍업 요구치
# (HMA_GAP_SLOW=600 -> min_start=750캔들=7.8일)가 17일치 데이터의 거의 절반을 잡아먹어
# 실질 평가구간이 17일이 아니라 9일 정도로 줄어들었기 때문. 라이브 봇은 실제로는 8/19
# 이전의 오랜 시장 이력으로 이미 지표가 다 "웜업"된 상태에서 8/19부터 거래 시작한 것이므로,
# 이를 재현하려면 웜업 여유분(최소 8일+버퍼)을 더 얹어서 데이터를 받은 뒤, 실제 거래 시작
# 시점(bot1 첫 entry_ts) 이후의 거래만 걸러내 비교해야 공정한 비교가 됨.
FETCH_DAYS = 60  # 17일 평가구간 + 워밍업(최소 7.8일) + 버퍼
EVAL_START_TS = 1787154303000  # bot1 실제 첫 거래 entry_ts (2026-08-19T15:45:03 UTC)
LEVERAGE = 10
SQUEEZE_ENTER_MULT = 0.85
BREAKOUT_MULT = 1.3

bcl.REENTRY_COOLDOWN_MS = 3600 * 1000  # 1시간 (2026-08-19 라이브 변경분)

LIVE_KWARGS = dict(
    profit_lock_trigger_pct=0.5,
    profit_lock_ratio=0.8,
    use_price_alignment_filter=True,
    stall_exit_candles=8, stall_exit_min_peak_pct=0.5,
    stall_exit_sl_pct=0.4,
    use_hma_direction_only=True,
    use_fast_breakout=True, fast_breakout_lookback=2, fast_breakout_mult=None,
    use_regime_exit=True,
)

# 실제 bot1 결과 (SSH로 trades.json 610건 직접 조회, 2026-08-19~2026-09-05)
BOT1_REAL = {
    "ADA": dict(n=51, win_rate=76.5, profit=-188.06),
    "ATOM": dict(n=30, win_rate=60.0, profit=-70.21),
    "AVAX": dict(n=34, win_rate=73.5, profit=288.10),
    "BCH": dict(n=62, win_rate=75.8, profit=411.20),
    "BNB": dict(n=42, win_rate=71.4, profit=235.09),
    "BTC": dict(n=39, win_rate=56.4, profit=-92.10),
    "DOGE": dict(n=42, win_rate=59.5, profit=-531.76),
    "DOT": dict(n=53, win_rate=79.2, profit=296.42),
    "ETH": dict(n=33, win_rate=66.7, profit=221.03),
    "LINK": dict(n=49, win_rate=69.4, profit=114.14),
    "LTC": dict(n=36, win_rate=72.2, profit=248.52),
    "NEAR": dict(n=29, win_rate=75.9, profit=89.44),
    "SOL": dict(n=38, win_rate=71.1, profit=-125.97),
    "TRX": dict(n=29, win_rate=58.6, profit=-90.71),
    "XRP": dict(n=43, win_rate=83.7, profit=193.45),
}
BOT1_TOTAL = dict(n=610, win_rate=70.8, pf=1.12, profit=998.58)


def summarize(trades):
    if not trades:
        return dict(n=0, win_rate=0, pf=0, profit=0)
    wins = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] <= 0]
    win_rate = len(wins) / len(trades) * 100
    gross_win = sum(t["profit"] for t in wins)
    gross_loss = -sum(t["profit"] for t in losses)
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    profit = sum(t["profit"] for t in trades)
    return dict(n=len(trades), win_rate=win_rate, pf=pf, profit=profit)


bcl.SQUEEZE_ENTER_MULT = SQUEEZE_ENTER_MULT
bcl.BREAKOUT_MULT = BREAKOUT_MULT
bcl.LEVERAGE = LEVERAGE

all_trades = []
results = {}
for coin in COINS:
    symbol = coin + "USDT"
    candles = bcl.fetch_klines(symbol, INTERVAL, FETCH_DAYS)
    trades, seed_end = bcl.run_backtest(candles, entry_sl_cap_pct=None, **LIVE_KWARGS)
    trades = [t for t in trades if t["entry_ts"] >= EVAL_START_TS]
    s = summarize(trades)
    results[coin] = s
    all_trades.extend(trades)
    r = BOT1_REAL[coin]
    pfn = f"{s['pf']:.2f}" if s['pf'] != float("inf") else "inf"
    print(f"[{coin:5s}] 백테스트: n={s['n']:3d} 승률={s['win_rate']:5.1f}% PF={pfn:>5s} 수익=${s['profit']:+9.2f}  "
          f"| 실제bot1: n={r['n']:3d} 승률={r['win_rate']:5.1f}% 수익=${r['profit']:+9.2f}", flush=True)

overall = summarize(all_trades)
pfn = f"{overall['pf']:.2f}" if overall['pf'] != float("inf") else "inf"
print(f"\n{'='*100}")
print(f"[전체] 백테스트: n={overall['n']} 승률={overall['win_rate']:.1f}% PF={pfn} 수익=${overall['profit']:+.2f}")
print(f"[전체] 실제bot1: n={BOT1_TOTAL['n']} 승률={BOT1_TOTAL['win_rate']:.1f}% PF={BOT1_TOTAL['pf']:.2f} 수익=${BOT1_TOTAL['profit']:+.2f}")
print("\n=== LIVE MATCH CHECK (15 COINS, 17 DAYS) COMPLETE ===", flush=True)
