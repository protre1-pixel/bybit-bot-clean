# -*- coding: utf-8 -*-
# 2026-08-07: "지금 15분봉이잖아, 1시간봉으로 다시 XRP 테스트해봐" 요청.
# 기존엔 15분봉을 기본 진입/청산 타임프레임으로 쓰고 1시간봉은 "상위추세 필터"로만
# 참고했는데, 이번엔 아예 진입/청산 자체를 1시간봉 기준으로 돌려서 15분봉 특유의
# 단기 노이즈(HEI 사례처럼 1분만에 SL 걸리는 것)에 덜 흔들리는지 확인.
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from datetime import datetime
import backtest_bb_squeeze as bt

SYMBOL = "XRPUSDT"
DAYS_1H = 100   # 15분봉 테스트 때와 동일 기간(100일), 캔들은 1시간봉이라 2400개 정도

out_lines = []
def emit(s=""):
    print(s)
    out_lines.append(s)


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


candles_1h = bt.fetch_klines(SYMBOL, "60", DAYS_1H)
emit(f"{SYMBOL} 1시간봉 {len(candles_1h)}개 "
     f"({datetime.fromtimestamp(candles_1h[0]['ts']/1000)} ~ {datetime.fromtimestamp(candles_1h[-1]['ts']/1000)})")
emit("")

configs = [
    ("A: 스퀴즈 1.5x 돌파만 (ADX 없음, HTF 없음)", dict(use_adx_filter=False)),
    ("B: 스퀴즈 1.5x + ADX 필터 (현재 라이브와 동일 조건, 타임프레임만 1h)", dict(use_adx_filter=True)),
]

orig = dict(
    STAGE1_TRIGGER_PCT=bt.STAGE1_TRIGGER_PCT,
    STAGE1_FEE_BUFFER_PCT=bt.STAGE1_FEE_BUFFER_PCT,
    STAGE2_LOCK_RATIO=bt.STAGE2_LOCK_RATIO,
)

emit("=== live_staging=True (실제 라이브 4단계 청산, Stage 파라미터는 기본값) ===")
for label, kwargs in configs:
    trades, seed = bt.run_backtest(candles_1h, breakout_mode="squeeze_avg", tp_mode="frozen",
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

emit("=== live_staging=False (참고: 단순화 청산, 신호 자체 품질만) ===")
for label, kwargs in configs:
    trades, seed = bt.run_backtest(candles_1h, breakout_mode="squeeze_avg", tp_mode="frozen",
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

with open("test_1h_base_xrp_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))
