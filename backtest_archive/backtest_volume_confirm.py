"""
2026-08-11 실험: (BB스퀴즈+HMA) 라이브 전략에 거래량확인 필터 추가 검증.

클로드/bybit-bot(별도 연구 프로젝트)의 strategy_volume_confirmed.py에서 "돌파 캔들의
거래량이 직전 평균 대비 확실히 커야 진짜 돌파로 인정" 조건을 추가했을 때 4h 기준으로
개선이 확인됐던 패턴을, 지금 라이브 배포된 BB스퀴즈+HMA 전략(backtest_current_live.py)의
돌파 감지 지점에 그대로 이식해서 효과가 있는지 확인.

기존 라이브 전략은 이미 squeeze_status=="squeeze"에서 폭이 급확장될 때(가짜 돌파/휩쏘 포함)
바로 진입하는데, 거래량 확인을 추가하면 신호 수는 줄지만(가짜 돌파 걸러짐) 승률/PF가 개선
되는지가 핵심 질문.

사용법: python backtest_volume_confirm.py [SYMBOL] [DAYS] [SYMBOL2 ...]
  (backtest_current_live.py / backtest_dual_tf.py와 동일한 argv 관례 - import 시
   그쪽 모듈 스코프의 sys.argv[1]/[2] 파싱과 위치가 어긋나면 안 되므로 맞춤)
  예) python backtest_volume_confirm.py XRPUSDT 400 XRPUSDT ETHUSDT BTCUSDT SOLUSDT
"""
import sys
from datetime import datetime

from backtest_current_live import fetch_klines, run_backtest, summarize, INTERVAL, DAYS

VOLUME_MULTS = [None, 1.2, 1.5, 2.0]  # None = 기존(거래량확인 없음, baseline)


if __name__ == "__main__":
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]

    for sym in coins:
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 {INTERVAL}분봉(1시간봉) 데이터 수집 중...", flush=True)
        candles = fetch_klines(sym, INTERVAL, DAYS)
        print(f"캔들 {len(candles)}개 수집 완료 "
              f"({datetime.fromtimestamp(candles[0]['ts']/1000)} ~ {datetime.fromtimestamp(candles[-1]['ts']/1000)})",
              flush=True)

        for vmult in VOLUME_MULTS:
            trades, final_seed = run_backtest(candles, volume_mult=vmult)
            label = f"{sym} volume_mult={vmult}" if vmult is not None else f"{sym} baseline(거래량확인 없음)"
            summarize(label, trades, final_seed)

    print("\n\n=== VOLUME CONFIRM TEST COMPLETE ===", flush=True)
