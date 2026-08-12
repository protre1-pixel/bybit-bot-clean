"""
2026-08-06: v9 DIRECT 트리거(스퀴즈 전제조건 없이 cw > aw*mult 엣지 트리거)가
XRPUSDT 60일에서 배수를 올릴수록 좋아지는 패턴을 보였는데, 표본이 작아서
(2.5x는 6거래) 우연인지 재현되는 패턴인지 확인 필요.
여러 심볼 x 더 긴 기간 x 여러 배수로 스윕해서 일관성 확인.
결과는 콘솔 mojibake(cp949) 문제를 피하려고 UTF-8 파일로도 저장.
"""
import io
import sys
import time
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import backtest_bb_squeeze as bt

SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT"]
DAYS = 100
MULTS = [1.5, 2.0, 2.5, 3.0]

out_lines = []


def emit(s=""):
    print(s)
    out_lines.append(s)


for symbol in SYMBOLS:
    emit(f"\n\n########## {symbol} ({DAYS}일) ##########")
    candles = bt.fetch_klines(symbol, bt.INTERVAL, DAYS)
    emit(f"캔들 {len(candles)}개 ({datetime.fromtimestamp(candles[0]['ts']/1000)} ~ "
         f"{datetime.fromtimestamp(candles[-1]['ts']/1000)})")

    # 기준선: 기존 squeeze_avg + ADX/DI (v8)
    trades, seed = bt.run_backtest(candles, breakout_mode="squeeze_avg", tp_mode="frozen",
                                    sl_first=True, use_adx_filter=True)
    n = len(trades)
    if n:
        wins = [t for t in trades if t["profit"] > 0]
        wr = len(wins) / n * 100
        gw = sum(t["profit"] for t in wins)
        gl = -sum(t["profit"] for t in trades if t["profit"] <= 0)
        pf = gw / gl if gl > 0 else float("inf")
        ret = (seed - bt.SEED) / bt.SEED * 100
        emit(f"[baseline squeeze_avg+ADX/DI] 거래{n} 승률{wr:.1f}% PF{pf:.2f} 수익률{ret:+.2f}%")
    else:
        emit("[baseline squeeze_avg+ADX/DI] 거래 없음")

    for mult in MULTS:
        for label_suffix, use_adx in [("+ADX/DI", True), ("필터없음", False)]:
            trades, seed = bt.run_backtest(candles, breakout_mode="direct", tp_mode="frozen",
                                            sl_first=True, use_adx_filter=use_adx, direct_mult=mult)
            n = len(trades)
            if n == 0:
                emit(f"[DIRECT {mult}x {label_suffix}] 거래 없음")
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
            emit(f"[DIRECT {mult}x {label_suffix}] 거래{n:3d} 승률{wr:5.1f}% PF{pf:5.2f} "
                 f"수익률{ret:+7.2f}% MDD{mdd:5.1f}%")

with open("sweep_direct_multi_results.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))
