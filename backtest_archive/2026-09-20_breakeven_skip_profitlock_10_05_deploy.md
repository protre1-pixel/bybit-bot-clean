# 2026-09-20: 본전방어 SKIP + profit_lock(트리거1.0%/비율0.5) 실거래 배포

## 배경
사용자 피드백: "trend_follow 단계에서도 수익률이 1% 이상을 못 넘긴다", "지금 수익을 너무
짧게 끊어 먹는 경향이 있다". trend_follow 트레일링을 구성하는 3개 요소 중:

1. **본전방어** (peak수익 >= `MIN_PROFIT_FOR_BREAKEVEN_PCT`면 SL을 진입가+0.15%로) → **SKIP**
2. **HMA갭 수축 트레일링** (갭이 피크의 40% 밑으로 줄면 최고가 대비 0.6% 트레일) → **불변**
3. **profit_lock** (peak수익 >= 트리거면 그 후로 "peak×비율" 사수) → 트리거 0.8%→**1.0%**,
   비율 0.6→**0.5**로 변경

## 백테스트 결과 (test_trend_follow_exit_tune_1h_15coin_1y.py, 15코인·1시간봉·1년,
BTC 공유게이트 lookback=4h)

| 구분 | 거래수 | 승률 | PF | 순수익 | 평균보유h | 근사MDD |
|---|---|---|---|---|---|---|
| A) 기존(본전방어 ON 0.4% + profit_lock 0.8%/0.6) | 748 | 82.6% | 1.48 | +$22,385.03 | 3.9h | 21.5% |
| B) 변경(본전방어 SKIP + profit_lock 1.0%/0.5) | 706 | 74.2% | 1.08 | +$2,784.51 | 7.8h | 35.2% |

**백테스트상으로는 명확히 악화**(순수익 -87%, 승률/PF/MDD 전부 악화)로 나왔음을 배포 전
사용자에게 보고. 사용자는 결과를 인지한 상태로 "실전이랑 다를 수 있으니 이대로 다시
테스트 해보겠다"는 취지로 실거래 재검증을 명시적으로 요청 → 그대로 배포.

## 변경 내용 (`app/services/trading_service.py`)

```
MIN_PROFIT_FOR_BREAKEVEN_PCT = 0.3   → 1e9   (도달 불가능한 값 → 본전방어 분기 사실상 SKIP)
PROFIT_LOCK_TRIGGER_PCT      = 0.8   → 1.0
PROFIT_LOCK_RATIO            = 0.6   → 0.5
```

`HMA_GAP_*` 관련 상수(FAST/SLOW/CONTRACTION_RATIO/EXIT_BUFFER_PCT)는 요청대로 손대지 않음.

## 배포 절차
- bot1/bot2 무포지션 확인 (양쪽 6개 지갑 모두 `is_active=False`) 후 진행.
- `trading_service.py.bak_20260920_212317`로 양쪽 서버 백업.
- scp로 갱신 파일 전송, `python3 -m py_compile` 양쪽 통과 확인.
- `pm2 restart bybit-bot1 bybit-bot2` — 재시작 로그 클린 확인(재시작 이전부터 있던 Bybit
  API rate-limit 재시도 에러는 무관한 기존 노이즈).

## 후속 조치
실거래 결과 보고 재조정 가능. 특히 본전방어 SKIP은 되돌릴 경우 `MIN_PROFIT_FOR_BREAKEVEN_PCT`를
1e9에서 다시 낮은 값(예: 0.3)으로만 바꾸면 됨(로직 자체는 그대로 남아있어 상수만 복구하면
즉시 재활성화).
