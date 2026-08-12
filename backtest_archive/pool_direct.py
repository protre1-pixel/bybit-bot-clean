import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import backtest_bb_squeeze as bt

SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT"]
DAYS = 100
MULTS = [1.5, 2.0, 2.5, 3.0]

data = {s: bt.fetch_klines(s, bt.INTERVAL, DAYS) for s in SYMBOLS}

for mult in MULTS:
    for use_adx in [True, False]:
        pooled = []
        for s, candles in data.items():
            trades, seed = bt.run_backtest(candles, breakout_mode="direct", tp_mode="frozen",
                                            sl_first=True, use_adx_filter=use_adx, direct_mult=mult)
            pooled.extend(trades)
        n = len(pooled)
        if n == 0:
            print(f"[POOLED {mult}x {'ADX/DI' if use_adx else 'no-filter'}] 거래 없음")
            continue
        wins = [t for t in pooled if t["profit"] > 0]
        wr = len(wins) / n * 100
        gw = sum(t["profit"] for t in wins)
        gl = -sum(t["profit"] for t in pooled if t["profit"] <= 0)
        pf = gw / gl if gl > 0 else float("inf")
        net = sum(t["profit"] for t in pooled)
        # 4개 코인 각각 $1000 시작 (합 $4000) 기준 총수익률
        ret = net / (4 * bt.SEED) * 100
        print(f"[POOLED {mult}x {'ADX/DI' if use_adx else 'no-filter':10s}] 거래{n:3d} 승률{wr:5.1f}% PF{pf:5.2f} 합산순익${net:+8.2f} (4000시드대비{ret:+6.2f}%)")

# baseline pooled for comparison
pooled = []
for s, candles in data.items():
    trades, seed = bt.run_backtest(candles, breakout_mode="squeeze_avg", tp_mode="frozen",
                                    sl_first=True, use_adx_filter=True)
    pooled.extend(trades)
n = len(pooled)
wins = [t for t in pooled if t["profit"] > 0]
wr = len(wins) / n * 100
gw = sum(t["profit"] for t in wins)
gl = -sum(t["profit"] for t in pooled if t["profit"] <= 0)
pf = gw / gl if gl > 0 else float("inf")
net = sum(t["profit"] for t in pooled)
ret = net / (4 * bt.SEED) * 100
print(f"[POOLED baseline squeeze_avg+ADX] 거래{n:3d} 승률{wr:5.1f}% PF{pf:5.2f} 합산순익${net:+8.2f} (4000시드대비{ret:+6.2f}%)")
