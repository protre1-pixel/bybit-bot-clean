"""2026-08-11 실험: 15분봉 완전복귀(backtest_15m_v2.py에서 -92~-98%로 참패 확인됨) 원인 중
하나가 "30분 재진입 쿨다운"일 가능성 검증. 1시간봉에서는 최소 캔들 간격(60분)이 쿨다운(30분)
보다 길어서 이 로직이 사실상 no-op였는데(backtest_no_cooldown.py로 확인), 15분봉에서는
캔들 간격(15분)이 쿨다운(30분)보다 짧아서 청산 직후 1~2개 캔들의 재진입 기회를 실제로
막고 있었을 것 - 그 규제를 없애면 좋은 재진입 타이밍을 놓치지 않아 개선될지 확인.

profit_lock(2.0/0.85)은 정확히 반영. 청산 로직은 기존(HMA200 Break) 그대로.

사용법: python backtest_no_cooldown_15m.py [SYMBOL] [DAYS] [SYMBOL2 ...]
"""
import sys
from datetime import datetime

import backtest_current_live as bcl

DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else bcl.DAYS
PLT, PLR = 2.0, 0.85  # 현재 라이브 profit_lock 값

if __name__ == "__main__":
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]

    for sym in coins:
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 15분봉 데이터 수집 중...", flush=True)
        candles = bcl.fetch_klines(sym, "15", DAYS)
        print(f"캔들 {len(candles)}개 수집 완료 "
              f"({datetime.fromtimestamp(candles[0]['ts']/1000)} ~ {datetime.fromtimestamp(candles[-1]['ts']/1000)})",
              flush=True)

        # 기존: 쿨다운 30분
        bcl.REENTRY_COOLDOWN_MS = 1800 * 1000
        trades, seed = bcl.run_backtest(candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR)
        bcl.summarize(f"{sym} 15분봉 쿨다운30분", trades, seed)

        # 신규: 쿨다운 제거
        bcl.REENTRY_COOLDOWN_MS = 0
        trades, seed = bcl.run_backtest(candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR)
        bcl.summarize(f"{sym} 15분봉 쿨다운없음", trades, seed)

    print("\n\n=== 15M NO-COOLDOWN TEST COMPLETE ===", flush=True)
