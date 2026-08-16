"""
2026-08-14: 사용자 실거래(BTC, 롱진입 15분만에 손절) 관찰 - "스퀴즈+양봉+HMA정배열로
롱진입하면, 장대양봉이 아닌 한 거의 다음 봉(15분)에 바로 HMA200 Break로 손절되는 거
아니냐?"는 구조적 의심을 실제 데이터로 검증.

가설: 진입 시점에 가격이 HMA200 대비 확보한 버퍼(%)가 작을수록, 다음 캔들의 정상적인
노이즈만으로도 HMA200 아래로 밀려서 최소 보유시간(1캔들=15분)만에 손절될 확률이 높다.

실전 로직 그대로(use_hma_regime_filter=True) XRP/ETH/BTC/SOL 365일 15분봉으로 확인.
"""
import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

bcl.SQUEEZE_ENTER_MULT = 0.7
bcl.BREAKOUT_MULT = 1.6

INTERVAL = "15"
DAYS = 365
COINS = ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]

all_break_trades = []

for sym in COINS:
    candles = bcl.fetch_klines(sym, INTERVAL, DAYS)
    ts_to_idx = {c["ts"]: i for i, c in enumerate(candles)}
    trades, _ = bcl.run_backtest(candles, use_hma_regime_filter=True)

    breaks = [t for t in trades if t["reason"] == "HMA200 Break"]
    print(f"[{sym}] 전체거래 {len(trades)}건, HMA200 Break {len(breaks)}건 ({len(breaks)/len(trades)*100:.1f}%)")

    for tr in breaks:
        idx = ts_to_idx.get(tr["entry_ts"])
        if idx is None:
            continue
        h200 = bcl.hma_at(candles, idx, bcl.HMA_ENTRY_PERIOD)
        if h200 is None:
            continue
        hma200_at_entry = h200["hma"]
        entry_price = tr["entry"]
        if tr["side"] == "long":
            buffer_pct = (entry_price - hma200_at_entry) / entry_price * 100
        else:
            buffer_pct = (hma200_at_entry - entry_price) / entry_price * 100
        all_break_trades.append({
            "sym": sym, "hold_h": tr["hold_h"], "buffer_pct": buffer_pct, "profit": tr["profit"],
        })

hold = np.array([t["hold_h"] for t in all_break_trades])
buf = np.array([t["buffer_pct"] for t in all_break_trades])

print(f"\n{'='*60}")
print(f"HMA200 Break 종료 거래 전체: {len(all_break_trades)}건")
print(f"  보유시간 = 0.25h(최소, 1캔들=15분) 인 비율: {(hold <= 0.26).mean()*100:.1f}%")
print(f"  보유시간 <= 0.5h(2캔들) 인 비율: {(hold <= 0.51).mean()*100:.1f}%")
print(f"  보유시간 <= 1.0h(4캔들) 인 비율: {(hold <= 1.01).mean()*100:.1f}%")
print(f"  보유시간 평균: {hold.mean():.2f}h  중앙값: {np.median(hold):.2f}h")

print(f"\n진입 시점 HMA200 버퍼(%) 분포:")
print(f"  평균 {buf.mean():.3f}%  중앙값 {np.median(buf):.3f}%")
for lvl in [0.0, 0.1, 0.2, 0.3, 0.5]:
    print(f"  버퍼 <= {lvl:.2f}% 인 비율: {(buf <= lvl).mean()*100:.1f}%")

# 15분(최소보유)로 끊긴 것들만 따로 - 버퍼가 특히 작은지 확인
quick = hold <= 0.26
slow = hold > 0.26
print(f"\n15분만에 끊긴 거래({quick.sum()}건) 진입버퍼 평균: {buf[quick].mean():.3f}%")
print(f"15분보다 오래 버틴 거래({slow.sum()}건) 진입버퍼 평균: {buf[slow].mean():.3f}%")
