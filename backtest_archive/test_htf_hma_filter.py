# -*- coding: utf-8 -*-
# 2026-08-07: "지금 15분봉 안에서만 다 판단하지, 1시간/4시간봉 상위 추세는 안 보잖아"
# 라는 지적 -> 1h/4h HMA200/600 정배열(골든)/역배열(데드)을 상위 추세 필터로 붙여서,
# 지금 라이브 진입 로직(squeeze_avg 1.5x + ADX)이 상위 추세와 같은 방향일 때만
# 진입하도록 제한하면 실제로 개선되는지 확인.
import io, sys, bisect
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np
from datetime import datetime
import backtest_bb_squeeze as bt

SYMBOL = "XRPUSDT"
DAYS_15M = 100     # 15분봉 진입/청산 백테스트 기간 (기존 test_live_staging.py와 동일)
DAYS_4H = 400       # 4시간봉: HMA600 워밍업(100일치) + 테스트기간(100일) 감안 여유있게
DAYS_1H = 160       # 1시간봉: HMA600 워밍업(25일치) + 테스트기간(100일) 감안 여유있게

out_lines = []
def emit(s=""):
    print(s)
    out_lines.append(s)


def hma_series(values, period):
    half = period // 2
    sq = int(np.sqrt(period))
    wma1 = bt.wma(values, half)
    wma2 = bt.wma(values, period)
    diff = 2 * wma1 - wma2
    return bt.wma(diff, sq)


def build_htf_trend_fn(htf_candles, hma200, hma600, interval_ms):
    """15분봉 캔들 시각(ts)을 받아 그 시점까지 이미 "확정 완료"된 가장 최근 상위
    타임프레임 캔들의 HMA200/600 정배열 상태를 반환. 미래 데이터 참조(lookahead)
    방지를 위해 해당 상위 캔들의 종료시각(open_ts + interval)이 ts를 넘지 않는
    캔들만 사용."""
    ts_list = [c["ts"] for c in htf_candles]

    def fn(ts):
        idx = bisect.bisect_right(ts_list, ts) - 1
        while idx >= 0 and ts_list[idx] + interval_ms > ts:
            idx -= 1
        if idx < 0:
            return None
        h2, h6 = hma200[idx], hma600[idx]
        if np.isnan(h2) or np.isnan(h6):
            return None
        if h2 > h6:
            return "up"
        elif h2 < h6:
            return "down"
        return None

    return fn


def stats(trades):
    n = len(trades)
    if n == 0:
        return None
    seed = bt.SEED
    wins = [t for t in trades if t["profit"] > 0]
    wr = len(wins) / n * 100
    gw = sum(t["profit"] for t in wins)
    gl = -sum(t["profit"] for t in trades if t["profit"] <= 0)
    pf = gw / gl if gl > 0 else float("inf")
    curve = [seed]
    s = seed
    for t in trades:
        s += t["profit"]
        curve.append(s)
    ret = (s - seed) / seed * 100
    peak = curve[0]
    mdd = 0
    for v in curve:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak * 100)
    reason_counts = {}
    for t in trades:
        reason_counts[t["reason"]] = reason_counts.get(t["reason"], 0) + 1
    return n, wr, pf, ret, mdd, reason_counts


emit(f"{SYMBOL} 상위 타임프레임(1h/4h) HMA200/600 정배열 추세필터 테스트")
emit("")

candles_15m = bt.fetch_klines(SYMBOL, "15", DAYS_15M)
emit(f"15분봉 {len(candles_15m)}개 ({datetime.fromtimestamp(candles_15m[0]['ts']/1000)} ~ {datetime.fromtimestamp(candles_15m[-1]['ts']/1000)})")

candles_4h = bt.fetch_klines(SYMBOL, "240", DAYS_4H)
close_4h = np.array([c["close"] for c in candles_4h])
hma200_4h = hma_series(close_4h, 200)
hma600_4h = hma_series(close_4h, 600)
first_valid_4h = next((i for i in range(len(candles_4h)) if not np.isnan(hma600_4h[i])), None)
emit(f"4시간봉 {len(candles_4h)}개, HMA600 유효 시작: "
     f"{datetime.fromtimestamp(candles_4h[first_valid_4h]['ts']/1000) if first_valid_4h else 'N/A'}")

candles_1h = bt.fetch_klines(SYMBOL, "60", DAYS_1H)
close_1h = np.array([c["close"] for c in candles_1h])
hma200_1h = hma_series(close_1h, 200)
hma600_1h = hma_series(close_1h, 600)
first_valid_1h = next((i for i in range(len(candles_1h)) if not np.isnan(hma600_1h[i])), None)
emit(f"1시간봉 {len(candles_1h)}개, HMA600 유효 시작: "
     f"{datetime.fromtimestamp(candles_1h[first_valid_1h]['ts']/1000) if first_valid_1h else 'N/A'}")
emit("")

htf_fn_4h = build_htf_trend_fn(candles_4h, hma200_4h, hma600_4h, 4 * 3600 * 1000)
htf_fn_1h = build_htf_trend_fn(candles_1h, hma200_1h, hma600_1h, 3600 * 1000)

configs = [
    ("A: 현재 라이브 (ADX만, HTF필터 없음)", dict(use_adx_filter=True, htf_trend_fn=None)),
    ("B: 현재 라이브 + HTF 4h HMA200/600 정배열", dict(use_adx_filter=True, htf_trend_fn=htf_fn_4h)),
    ("C: 현재 라이브 + HTF 1h HMA200/600 정배열", dict(use_adx_filter=True, htf_trend_fn=htf_fn_1h)),
    ("D: ADX 없이 HTF 4h 필터만", dict(use_adx_filter=False, htf_trend_fn=htf_fn_4h)),
    ("E: ADX 없이 HTF 1h 필터만", dict(use_adx_filter=False, htf_trend_fn=htf_fn_1h)),
]

emit("=== live_staging=True (실제 라이브 4단계 청산 로직 그대로) ===")
for label, kwargs in configs:
    trades, seed = bt.run_backtest(candles_15m, breakout_mode="squeeze_avg", tp_mode="frozen",
                                    sl_first=True, squeeze_mult=1.5, live_staging=True, **kwargs)
    result = stats(trades)
    if result is None:
        emit(f"[{label}] 거래 없음")
        continue
    n, wr, pf, ret, mdd, reason_counts = result
    reason_str = ", ".join(f"{k}:{v}" for k, v in sorted(reason_counts.items()))
    emit(f"[{label}]")
    emit(f"  거래{n:3d} 승률{wr:5.1f}% PF{pf:5.2f} 수익률{ret:+7.2f}% MDD{mdd:5.1f}%")
    emit(f"  청산사유: {reason_str}")
emit("")

emit("=== 참고: live_staging=False (기존 단순화 normal/trailing 2단계, 청산모델 왜곡 배제하고 신호 자체 품질만 비교) ===")
for label, kwargs in configs:
    trades, seed = bt.run_backtest(candles_15m, breakout_mode="squeeze_avg", tp_mode="frozen",
                                    sl_first=True, squeeze_mult=1.5, live_staging=False, **kwargs)
    result = stats(trades)
    if result is None:
        emit(f"[{label}] 거래 없음")
        continue
    n, wr, pf, ret, mdd, reason_counts = result
    reason_str = ", ".join(f"{k}:{v}" for k, v in sorted(reason_counts.items()))
    emit(f"[{label}]")
    emit(f"  거래{n:3d} 승률{wr:5.1f}% PF{pf:5.2f} 수익률{ret:+7.2f}% MDD{mdd:5.1f}%")
    emit(f"  청산사유: {reason_str}")
emit("")

with open("test_htf_hma_filter_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))
