# -*- coding: utf-8 -*-
# 2026-08-07: live_staging=True 4단계 계단식 SL의 Stage1/2/3 파라미터를 스윕해서
# "얕은 눌림에 너무 빨리 끊기는" 문제(Stage3 트레일링 도달 0건)를 완화할 수 있는지 확인.
# XRP만, 진입조건 두 가지(squeeze_avg 1.5x / squeeze 최저점 1.15x, 둘 다 ADX/DI 필터)로 테스트.
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from datetime import datetime
import backtest_bb_squeeze as bt

SYMBOL = "XRPUSDT"
DAYS = 100

out_lines = []
def emit(s=""):
    print(s)
    out_lines.append(s)

candles = bt.fetch_klines(SYMBOL, bt.INTERVAL, DAYS)
emit(f"{SYMBOL} 캔들 {len(candles)}개 ({datetime.fromtimestamp(candles[0]['ts']/1000)} ~ {datetime.fromtimestamp(candles[-1]['ts']/1000)})")
emit("Stage1/2/3 파라미터 스윕 (live_staging=True 고정)")
emit("")

# label, stage1_trigger, stage2_trigger, stage2_lock_ratio, stage3_trigger, stage3_trail_ratio, stage3_trail_min
stage_configs = [
    ("A: 현재(baseline)      S1=1.0 S2=2.0(lock50%) S3=5.0(trail30%,min3%)", 1.0, 2.0, 0.5, 5.0, 0.3, 3.0),
    ("B: lock 완화           S1=1.0 S2=2.0(lock30%) S3=5.0(trail30%,min3%)", 1.0, 2.0, 0.3, 5.0, 0.3, 3.0),
    ("C: 트리거 지연         S1=1.5 S2=3.0(lock50%) S3=6.0(trail30%,min3%)", 1.5, 3.0, 0.5, 6.0, 0.3, 3.0),
    ("D: 지연+완화 combo     S1=1.5 S2=3.0(lock30%) S3=6.0(trail30%,min3%)", 1.5, 3.0, 0.3, 6.0, 0.3, 3.0),
    ("E: 더 크게 지연+완화   S1=2.0 S2=4.0(lock30%) S3=8.0(trail30%,min3%)", 2.0, 4.0, 0.3, 8.0, 0.3, 3.0),
]

entry_configs = [
    ("squeeze_avg 1.5x + ADX/DI (현재 라이브 진입)", "squeeze_avg", 1.5, True),
    ("squeeze(최저점) 1.15x + ADX/DI", "squeeze", 1.15, True),
]

orig = dict(
    STAGE1_TRIGGER_PCT=bt.STAGE1_TRIGGER_PCT,
    STAGE2_TRIGGER_PCT=bt.STAGE2_TRIGGER_PCT,
    STAGE2_LOCK_RATIO=bt.STAGE2_LOCK_RATIO,
    STAGE3_TRIGGER_PCT=bt.STAGE3_TRIGGER_PCT,
    STAGE3_TRAIL_RATIO=bt.STAGE3_TRAIL_RATIO,
    STAGE3_TRAIL_MIN_PCT=bt.STAGE3_TRAIL_MIN_PCT,
)

try:
    for entry_label, mode, mult, use_adx in entry_configs:
        emit(f"===== 진입: {entry_label} =====")
        for label, s1, s2, lock, s3, trail_ratio, trail_min in stage_configs:
            bt.STAGE1_TRIGGER_PCT = s1
            bt.STAGE2_TRIGGER_PCT = s2
            bt.STAGE2_LOCK_RATIO = lock
            bt.STAGE3_TRIGGER_PCT = s3
            bt.STAGE3_TRAIL_RATIO = trail_ratio
            bt.STAGE3_TRAIL_MIN_PCT = trail_min

            trades, seed = bt.run_backtest(candles, breakout_mode=mode, tp_mode="frozen",
                                            sl_first=True, use_adx_filter=use_adx, squeeze_mult=mult,
                                            live_staging=True)
            n = len(trades)
            if n == 0:
                emit(f"  [{label}] 거래 없음")
                continue
            wins = [t for t in trades if t["profit"] > 0]
            wr = len(wins) / n * 100
            gw = sum(t["profit"] for t in wins)
            gl = -sum(t["profit"] for t in trades if t["profit"] <= 0)
            pf = gw / gl if gl > 0 else float("inf")
            ret = (seed - bt.SEED) / bt.SEED * 100
            curve = [bt.SEED]
            s = bt.SEED
            for t in trades:
                s += t["profit"]
                curve.append(s)
            peak = curve[0]
            mdd = 0
            for v in curve:
                peak = max(peak, v)
                mdd = max(mdd, (peak - v) / peak * 100)
            reason_counts = {}
            for t in trades:
                reason_counts[t["reason"]] = reason_counts.get(t["reason"], 0) + 1
            reason_str = ", ".join(f"{k}:{v}" for k, v in sorted(reason_counts.items()))
            emit(f"  [{label}]")
            emit(f"    거래{n:3d} 승률{wr:5.1f}% PF{pf:5.2f} 수익률{ret:+7.2f}% MDD{mdd:5.1f}%")
            emit(f"    청산사유: {reason_str}")
        emit("")
finally:
    bt.STAGE1_TRIGGER_PCT = orig["STAGE1_TRIGGER_PCT"]
    bt.STAGE2_TRIGGER_PCT = orig["STAGE2_TRIGGER_PCT"]
    bt.STAGE2_LOCK_RATIO = orig["STAGE2_LOCK_RATIO"]
    bt.STAGE3_TRIGGER_PCT = orig["STAGE3_TRIGGER_PCT"]
    bt.STAGE3_TRAIL_RATIO = orig["STAGE3_TRAIL_RATIO"]
    bt.STAGE3_TRAIL_MIN_PCT = orig["STAGE3_TRAIL_MIN_PCT"]

with open("test_stage_sweep_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))
