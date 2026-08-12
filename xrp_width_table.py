# -*- coding: utf-8 -*-
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from datetime import datetime, timedelta, timezone
import backtest_bb_squeeze as bt

KST = timezone(timedelta(hours=9))

candles = bt.fetch_klines("XRPUSDT", bt.INTERVAL, 3)  # 최근 3일치면 오늘 00시 + lookback 100개 확보 충분
print(f"총 캔들 {len(candles)}개, 마지막: {datetime.fromtimestamp(candles[-1]['ts']/1000, KST)}")

today_start = datetime(2026, 8, 6, 18, 0, 0, tzinfo=KST)
today_start_ts = int(today_start.timestamp() * 1000)

rows = []
squeeze_status = "normal"
squeeze_avg = None
squeeze_count = 0
squeeze_sum = 0.0

for t in range(len(candles)):
    info = bt.width_info_at(candles, t)
    if info is None:
        continue
    ts = candles[t]["ts"]
    cw = info["current_width"]
    aw = info["avg_width"]

    # 라이브와 동일한 squeeze 상태머신 시뮬
    note = ""
    if squeeze_status == "normal":
        if cw < aw * bt.SQUEEZE_ENTER_MULT:
            squeeze_status = "squeeze"
            squeeze_sum = cw
            squeeze_count = 1
            squeeze_avg = cw
            note = "SQUEEZE진입"
    elif squeeze_status == "squeeze":
        if cw > squeeze_avg * bt.BREAKOUT_MULT:
            direction = "LONG" if info["candle_close"] > info["candle_open"] else ("SHORT" if info["candle_close"] < info["candle_open"] else "-")
            note = f"BREAKOUT!{direction}(sqavg={squeeze_avg:.6f})"
            squeeze_status = "normal"
        else:
            squeeze_sum += cw
            squeeze_count += 1
            squeeze_avg = squeeze_sum / squeeze_count

    if ts >= today_start_ts:
        kst_time = datetime.fromtimestamp(ts/1000, KST)
        ratio = cw / aw if aw else 0
        rows.append((kst_time, cw, aw, ratio, squeeze_status, note))

print(f"\n{'시각':^14} {'현재폭':>10} {'평균폭':>10} {'비율':>7} {'상태':^8} 비고")
for kst_time, cw, aw, ratio, status, note in rows:
    print(f"{kst_time.strftime('%m-%d %H:%M'):^14} {cw:>10.6f} {aw:>10.6f} {ratio:>6.2f}x {status:^8} {note}")

with open("xrp_width_table_result.txt", "w", encoding="utf-8") as f:
    f.write(f"{'시각':^14} {'현재폭':>10} {'평균폭':>10} {'비율':>7} {'상태':^8} 비고\n")
    for kst_time, cw, aw, ratio, status, note in rows:
        f.write(f"{kst_time.strftime('%m-%d %H:%M'):^14} {cw:>10.6f} {aw:>10.6f} {ratio:>6.2f}x {status:^8} {note}\n")
