# 2026-08-19 배포: 대장주 15종 화이트리스트 + 레버리지 10x + 홀드윈도우 완전 제거

## 배경

BEAT(innovation 타입 잡코인) 실거래에서 큰 손실(bot2 기준 $-300.25) 발생. 원인 진단 결과,
거래량+변동성 기반 동적 코인 선별로는 잡코인(BEAT/JCT/KORU/SNXX 등)이 계속 후보에 섞여드는
것을 확인 — 심지어 변동성 가중치를 빼고 순수 거래대금 순위만 봐도 SNXX/KORU/BEAT가 상위
10~15위 안에 듦(실제로 거래량 자체가 큰 코인들이라 거래량 필터로는 못 걸러냄). 사용자 지시로
"대장주"만 고정 화이트리스트로 거래하도록 변경.

이어서 사용자가 "3시간 홀드 sl 8.5 빼고 돌려보자"고 지시 → 처음엔 홀드윈도우 구조는 유지하고
그 안의 파국적 SL 체크만 끄는 것으로 구현(`HOLD_CAT_SL_ENABLED=False`)했으나, 사용자가 재차
"이제 3시간 홀드 같은게 없고 기존 로직대로 돌아갈껀데"라고 정정 → 홀드윈도우 게이트 자체를
완전 삭제하기로 최종 결정(commit 7e4e1a2 이전 동작으로 복귀, 34~37차 백테스트 기준 로직).

## 변경 내용

### 1. 대장주 15종 화이트리스트 (`app/services/coin_service.py`)
```python
MAJOR_COINS = [
    "btc", "eth", "sol", "xrp", "bnb", "ada", "doge", "avax",
    "link", "dot", "trx", "ltc", "bch", "atom", "near",
]
```
`get_top_coins_by_volume()`, `get_top_coins_by_volume_volatility()` 둘 다 이 목록 안에서만
거래량/변동성으로 순위를 매기도록 고정 (기존엔 Bybit 전체 선물 티커 top 50~100을 스캔).
이 목록은 시총/거래량 API로 검증한 게 아니라 통상적으로 메이저로 취급되는 코인을 수동으로
나열한 것 — 필요시 이 상수만 수정하면 됨.

### 2. 레버리지 기본값 5 → 10
`app/utils/helpers.py`, `app/routes/coins.py`, `app/routes/settings.py`, `app/routes/trading.py`,
`app/services/trading_service.py` — 새 코인/지갑 생성 시 기본 레버리지, 설정 조회 fallback 등
9곳 전부 변경.

### 3. 홀드윈도우(진입 후 3시간 청산로직 스킵) 완전 제거 (`app/services/trading_service.py`)
`HOLD_WINDOW_SEC`/`HOLD_CAT_SL_PCT`/`HOLD_CAT_SL_ENABLED` 상수 및 관련 게이트 로직을 전부
삭제. 진입 즉시 stall_exit/HMA200-Break/trend_follow/BB SL·TP가 바로 작동 (2026-08-18
도입 이전, 34~37차 백테스트 검증 당시의 로직으로 복귀). 거래소 SL 주문도 진입 시점에
정상 sl_price 그대로 즉시 걸림 (파국적 가격/무방비 구간 없음).

## 백테스트 대비 참고사항

37차(`backtest_archive/2026-08-19_sq085_bo13_deploy.md` 참고) 테스트에서 이미 거의 동일한
조합(SQ0.85/BO1.3 + 레버10x + 홀드윈도우 없음, 단 4코인)을 검증한 바 있고, 결과가 크게
악화됨을 확인(PF 1.17~1.23, MDD 40~70% — 당시 라이브였던 35차 PF 2.99~4.92, MDD 8.9~20.8%
대비 큰 악화). 그때 결론은 "레버리지 10x 자체가 악화 원인". 이번 배포는 코인 유니버스가
4종→15종 화이트리스트로 달라 37차와 정확히 같은 조합은 아니지만, 레버리지/홀드윈도우 구조는
동일 — 배포 전 이 사실을 사용자에게 명확히 알렸고, 사용자가 "실전이랑 테스트랑은 달라"라며
백테스트 결과와 무관하게 배포를 지시함. **이 정확한 조합(15종 화이트리스트+레버10x+
홀드없음)은 사전 백테스트 없이 실거래 배포됨.**

## 배포 절차

1. 배포 전 양쪽 인스턴스 오픈 포지션 확인: 둘 다 포지션 없음(직전에 BEAT 포지션이 구코드
   기준 정상 청산되어 종료됨 - bot1 -$12.40, bot2 -$300.25). bot1은 `mode=paper`, bot2는
   `BYBIT_DEMO=true`로 확인되어 실자금 리스크 없는 상태에서 진행.
2. 서버(`192.168.1.134`, user `protre`)에서 `bybit-bot1`/`bybit-bot2` 양쪽 6개 파일을
   `.bak_20260819_134531`로 백업 (coin_service.py, trading_service.py, helpers.py,
   coins.py, settings.py, trading.py).
3. 로컬 수정 파일 scp 배포 → 양쪽 `python3 -m py_compile` 통과 확인.
4. `pm2 restart bybit-bot1 bybit-bot2` → 재시작 로그 정상 확인, 에러 없음.

## 남은 이슈 (배포에는 포함 안 됨)

- **코드 배포만으로는 이미 저장된 state(`bot_state.json`)가 자동 갱신되지 않음**: 양쪽
  인스턴스 모두 `available_coins`에 여전히 구 잡코인 목록(soxl/hype/snxx/koru/beat/zec 등)이
  남아있고, 지갑 `leverage`도 여전히 5로 저장돼 있음. 새 화이트리스트/레버리지가 실제
  거래에 반영되려면 UI에서 코인 재선택(`/api/global-settings` POST) 또는 거래
  시작/초기화(`/api/trading/start`, `/api/trading/reset`)를 트리거해야 함 — 이번 배포
  범위에는 포함하지 않음(포지션 없는 상태 확인만 하고 코드만 교체).
