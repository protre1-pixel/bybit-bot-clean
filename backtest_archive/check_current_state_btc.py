"""
2026-08-14: 사용자가 보여준 BTC 15분봉 차트(박스권→급락→반등→2차급락, 현재 하락 가속중)가
실제로 지금 봇 로직(스퀴즈/브레이크아웃 상태, HMA200/600 정배열, 갭%) 기준으로 어떻게
읽히는지 실시간 데이터로 확인.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

SYMBOL = "BTCUSDT"
INTERVAL = "15"
DAYS = 30

candles = bcl.fetch_klines(SYMBOL, INTERVAL, DAYS)
n = len(candles)
t = n - 1
last = candles[t]
print(f"[{SYMBOL}] 캔들 {n}개, 최신봉 시각: {bcl.datetime.fromtimestamp(last['ts']/1000)}")
print(f"최신 종가: {last['close']}")

wi = bcl.width_info_at(candles, t)
if wi:
    ratio = wi["current_width"] / wi["avg_width"]
    print(f"\n[밴드폭] 현재폭={wi['current_width']:.6f}  평균폭={wi['avg_width']:.6f}  비율={ratio:.2f}배")
    print(f"  -> 스퀴즈 진입 기준(0.7배): {'스퀴즈권' if ratio < 0.7 else '스퀴즈 아님'}")
else:
    print("밴드폭 계산 불가(데이터 부족)")

regime = bcl.htf_trend_at(candles, t)
print(f"\n[HMA200/600 정배열] {regime}")

gap_info = bcl.hma_gap_at(candles, t)
if gap_info:
    gap_pct = abs(gap_info["gap"]) / last["close"] * 100
    print(f"[HMA갭] gap={gap_info['gap']:.4f}  gap%={gap_pct:.3f}%")
else:
    print("갭 계산 불가")

h200 = bcl.hma_at(candles, t, bcl.HMA_GAP_FAST)
h600 = bcl.hma_at(candles, t, bcl.HMA_GAP_SLOW)
if h200 and h600:
    print(f"[HMA200] {h200['hma']:.4f}   [HMA600] {h600['hma']:.4f}   [현재가] {last['close']:.4f}")

# 최근 20봉 요약(스퀴즈 상태 추적 시뮬레이션 - 마지막 상태만)
squeeze_status = "normal"
squeeze_width = None
for tt in range(max(bcl.WIDTH_FETCH_WINDOW + bcl.WIDTH_LOOKBACK + 5, 100), n):
    wi2 = bcl.width_info_at(candles, tt)
    if wi2 is None:
        continue
    cw = wi2["current_width"]
    aw = wi2["avg_width"]
    if squeeze_status == "normal":
        if cw < aw * bcl.SQUEEZE_ENTER_MULT:
            squeeze_status = "squeeze"
            squeeze_width = cw
    elif squeeze_status == "squeeze":
        if cw < squeeze_width:
            squeeze_width = cw
        if cw > squeeze_width * bcl.BREAKOUT_MULT:
            squeeze_status = "normal"

print(f"\n[상태머신 시뮬레이션 결과] 현재 squeeze_status = {squeeze_status}")
if squeeze_status == "squeeze":
    print(f"  스퀴즈 진입 후 최저폭 = {squeeze_width:.6f}, breakout 기준(1.6배) = {squeeze_width*1.6:.6f}, 현재폭={wi['current_width']:.6f}")
