"""2026-08-11 실험: 포지션 종료 후 30분 재진입 쿨다운(REENTRY_COOLDOWN_MS)을 없앴을 때
효과 검증. 현재 라이브(trading_service.py auto_trade)에도 "거래 종료 후 30분 이내는
자동거래 비활성화(재진입 방지)" 로직이 있음 - 이걸 제거하면 신호 자체는 그대로인데
청산 직후 바로 재진입 기회를 놓치지 않게 됨.

run_backtest()이 REENTRY_COOLDOWN_MS를 파라미터로 안 받고 backtest_current_live 모듈
전역변수를 직접 참조하므로, 모듈 자체를 import해서 그 속성을 0으로 몽키패치하는 방식으로
쿨다운을 끈 뒤 같은 run_backtest()를 재사용 (로직 중복 없이 정확히 같은 코드 경로 보장).

사용법: python backtest_no_cooldown.py [SYMBOL] [DAYS] [SYMBOL2 ...]
"""
import sys
from datetime import datetime

import backtest_current_live as bcl

DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else bcl.DAYS
PLT, PLR = 2.0, 0.85  # 현재 라이브 profit_lock 값

if __name__ == "__main__":
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]

    for sym in coins:
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 1시간봉 데이터 수집 중...", flush=True)
        candles = bcl.fetch_klines(sym, "60", DAYS)
        print(f"캔들 {len(candles)}개 수집 완료 "
              f"({datetime.fromtimestamp(candles[0]['ts']/1000)} ~ {datetime.fromtimestamp(candles[-1]['ts']/1000)})",
              flush=True)

        # 기존: 쿨다운 30분 (현재 라이브)
        bcl.REENTRY_COOLDOWN_MS = 1800 * 1000
        trades, seed = bcl.run_backtest(candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR)
        bcl.summarize(f"{sym} 쿨다운30분(현재라이브)", trades, seed)

        # 신규: 쿨다운 제거
        bcl.REENTRY_COOLDOWN_MS = 0
        trades, seed = bcl.run_backtest(candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR)
        bcl.summarize(f"{sym} 쿨다운없음", trades, seed)

    print("\n\n=== NO-COOLDOWN TEST COMPLETE ===", flush=True)
