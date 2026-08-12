# -*- coding: utf-8 -*-
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from datetime import datetime, timedelta, timezone
import backtest_bb_squeeze as bt

KST = timezone(timedelta(hours=9))
candles = bt.fetch_klines("XRPUSDT", bt.INTERVAL, 3)

today_start = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)
today_start_ts = int(today_start.timestamp() * 1000)

squeeze_status = "normal"
squeeze_min = None
fired = False

for t in range(len(candles)):
    info = bt.width_info_at(candles, t)
    if info is None:
        continue
    ts = candles[t]["ts"]
    cw = info["current_width"]
    aw = info["avg_width"]
    kst_time = datetime.fromtimestamp(ts/1000, KST)

    if squeeze_status == "normal":
        if cw < aw * bt.SQUEEZE_ENTER_MULT:
            squeeze_status = "squeeze"
            squeeze_min = cw
            if ts >= today_start_ts:
                print(f"{kst_time.strftime('%H:%M')} SQUEEZE 진입 (폭 {cw:.6f})")
    elif squeeze_status == "squeeze":
        # 최저점 기준 트리거 체크 (직전까지의 최저점 * 1.5)
        threshold = squeeze_min * bt.BREAKOUT_MULT
        if cw > threshold:
            direction = "LONG" if info["candle_close"] > info["candle_open"] else ("SHORT" if info["candle_close"] < info["candle_open"] else "-")
            if ts >= today_start_ts:
                print(f"{kst_time.strftime('%H:%M')} >>> 최저점기준 BREAKOUT! {direction} (폭 {cw:.6f} > 최저점 {squeeze_min:.6f} x1.5 = {threshold:.6f})")
            squeeze_status = "normal"
            fired = True
        else:
            squeeze_min = min(squeeze_min, cw)
            if ts >= today_start_ts:
                print(f"{kst_time.strftime('%H:%M')} squeeze중 (폭 {cw:.6f}, 최저점 {squeeze_min:.6f}, 커트라인 {squeeze_min*bt.BREAKOUT_MULT:.6f})")
