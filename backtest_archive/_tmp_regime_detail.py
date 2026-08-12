import backtest_current_live as bcl

bcl.SQUEEZE_ENTER_MULT = 0.5
bcl.BREAKOUT_MULT = 1.5

for sym in ["XRPUSDT", "ETHUSDT"]:
    candles = bcl.fetch_klines(sym, "60", 365)
    trades, seed = bcl.run_backtest(candles, profit_lock_trigger_pct=0.5, profit_lock_ratio=0.85,
                                     use_hma_regime_filter=True)
    bcl.summarize(f"{sym} 신규필터 상세", trades, seed)
    print("\n개별 거래:")
    for t in trades:
        print(f"  {t['side']:<5} entry={t['entry']:.4f} exit={t['exit']:.4f} pct={t['pct']:+.2f}% "
              f"profit=${t['profit']:.2f} reason={t['reason']} hold={t['hold_h']:.1f}h peak={t['peak_pct']:+.2f}%")
