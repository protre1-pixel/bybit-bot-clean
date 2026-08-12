"""2026-08-11 실험: normal 단계 "HMA200 Break" 하드컷의 손실 크기가 유독 큰 패턴 검증.

현재 라이브(1h) 백테스트 breakdown을 보면 코인마다 승률은 높은데(BTC 66.7%) PF가
낮은(0.43) "적게 먹고 크게 잃는" 구조가 보임 - HMA200 Break 건당 평균손실이
BTC -$49.58~-130.72, SOL -$130.72로 Trend Follow Stop 평균이익(+$3~96)보다 훨씬 큼.
가격이 HMA200을 살짝 스치기만 해도 즉시 전량 손절하는 구조라, 진짜 추세반전이 아니라
노이즈성 터치에도 크게 베일 가능성.

run_backtest()에 이미 존재하는 hma200_buffer_pct 파라미터(HMA200을 그만큼 더 넘어야
손절되도록 완충)를 지금까지 한 번도 스윕해본 적이 없어서, 이번에 1시간봉(현재 라이브
타임프레임) 기준으로 검증.

사용법: python backtest_hma_buffer.py [SYMBOL] [DAYS] [SYMBOL2 ...]
"""
import sys
from datetime import datetime

from backtest_current_live import fetch_klines, run_backtest, summarize, DAYS

BUFFERS = [0.0, 0.3, 0.5, 0.8, 1.2, 1.8]  # % - HMA200 대비 추가로 넘어야 손절

if __name__ == "__main__":
    coins = sys.argv[3:] if len(sys.argv) > 3 else ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]

    for sym in coins:
        print(f"\n{'#'*70}\n[{sym}] {DAYS}일치 1시간봉 데이터 수집 중...", flush=True)
        candles = fetch_klines(sym, "60", DAYS)
        print(f"캔들 {len(candles)}개 수집 완료 "
              f"({datetime.fromtimestamp(candles[0]['ts']/1000)} ~ {datetime.fromtimestamp(candles[-1]['ts']/1000)})",
              flush=True)

        for buf in BUFFERS:
            # 현재 라이브 profit_lock 값(trigger=2.0, ratio=0.85) 유지한 채 buffer만 스윕
            trades, final_seed = run_backtest(candles, hma200_buffer_pct=buf,
                                               profit_lock_trigger_pct=2.0, profit_lock_ratio=0.85)
            summarize(f"{sym} buffer={buf}%", trades, final_seed)

    print("\n\n=== HMA200 BUFFER SWEEP COMPLETE ===", flush=True)
