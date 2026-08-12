"""2026-08-11 실험: 라이브 전략을 다시 15분봉 전체(진입신호+포지션관리)로 되돌렸을 때의
성과를 사전 검증.

2026-08-10에 진입 신호(BB폭 스퀴즈/브레이크아웃)와 포지션관리(HMA200 하드컷,
trend_follow 단계 HMA갭 트레일링)를 전부 15분봉 -> 1시간봉으로 통일했는데, 신호 빈도가
너무 낮아서 다시 15분봉으로 되돌리는 걸 검토 중. run_backtest()는 candles 리스트만
받으면 되는 순수 함수라 15분봉 캔들을 그대로 넣으면 "완전 15분봉" 구성을 재현할 수 있음
(기간 상수 HMA_ENTRY_PERIOD=200/HMA_GAP_FAST=200/HMA_GAP_SLOW=600/BB_PERIOD=30 등은
그대로 유지 - 2026-08-10 변경은 timeframe 인자만 바꾼 것으로 확인됨, git 히스토리는
단일 커밋으로 squash되어 있어 대조 불가하지만 코드 주석상 그렇게 명시돼있음).

사용법: python backtest_15m.py [SYMBOL] [DAYS] [SYMBOL2 ...]
  예) python backtest_15m.py XRPUSDT 400 XRPUSDT ETHUSDT BTCUSDT SOLUSDT
"""
import sys
from datetime import datetime

from backtest_current_live import fetch_klines, run_backtest, summarize, DAYS

if __name__ == "__main__":
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]

    for sym in coins:
        for interval, label in [("15", "15분봉"), ("60", "1시간봉(현재라이브)")]:
            print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 {label} 데이터 수집 중...", flush=True)
            candles = fetch_klines(sym, interval, DAYS)
            print(f"캔들 {len(candles)}개 수집 완료 "
                  f"({datetime.fromtimestamp(candles[0]['ts']/1000)} ~ {datetime.fromtimestamp(candles[-1]['ts']/1000)})",
                  flush=True)

            trades, final_seed = run_backtest(candles)
            summarize(f"{sym} {label}", trades, final_seed)

    print("\n\n=== 15M REVERT TEST COMPLETE ===", flush=True)
