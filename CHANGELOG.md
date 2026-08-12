# CHANGELOG

## 2026-08-05

### Squeeze Breakout 진입 타이밍 수정
- **문제**: Breakout 판정 기준이 `avg_width`(최근 100개 15분봉≈25시간 평균 밴드폭)였음. 이 평균이 워낙 완만하게 움직여서, 실제로 밴드가 좁다가 확 넓어지는 시점보다 신호가 한참 늦게(때로는 급등/급락 후 되돌림·반등까지 지난 뒤에) 나가는 문제가 있었음. 실거래 예시 2건에서 진입 타점이 사용자가 원한 지점보다 눈에 띄게 늦은 것으로 확인됨.
- **수정**: `app/services/trading_service.py`의 `check_bollinger_band_signal()` — breakout 판정 기준을 "25시간 평균"이 아니라 "직전 squeeze 상태에서 가장 좁았던 폭(`squeeze_width`)"으로 변경. squeeze 상태가 지속되는 동안 폭이 더 좁아지면 저점을 계속 갱신하고, `current_width`가 그 저점의 `BREAKOUT_MULTIPLIER`(1.5)배를 넘는 즉시 신호 발동. 기존에 저장되던 `squeeze_width` 필드를 그대로 재사용하는 하위호환 변경이라 진행 중인 포지션이나 이미 squeeze 상태로 대기 중인 코인에는 영향 없음.

## 2026-08-04

### TP/SL 로직 수정
- **문제**: Normal 모드에서 가격이 유리하게 움직이지 않아도 볼린저밴드 폭이 변동성 수축으로 줄어들면 SL/TP가 계속 타이트해졌음 (브레이크아웃 직후 흔한 현상).
- **수정**: `app/services/trading_service.py` — `max_profit_price`가 새로운 유리한 극값을 갱신할 때만 BB 폭을 다시 계산해 SL/TP를 조정하도록 변경. 가격이 그대로거나 불리하게 움직이면 SL/TP 유지.

### 라이브 거래 안전성 수정
- **`close_trade()` 방향 버그**: 포지션 방향(롱/숏)과 무관하게 항상 매도 주문만 나가던 문제 수정. 숏 포지션 청산 시엔 매수(환매) 주문이 나가도록 분기 처리. (`app/services/trading_service.py`)
- **`reduceOnly` 플래그 추가**: 청산 주문이 실수로 새 포지션을 열거나 반대 포지션으로 뒤집는 것을 방지. (`app/services/order_service.py`)
- **주문 수량 반올림(lot size) 추가**: 심볼별 `qtyStep`/`minOrderQty`를 조회해 주문 수량을 맞춰서, 라이브 주문이 Bybit API에서 수량 정밀도 문제로 거부되는 것을 방지. (`app/services/order_service.py`)
- **`bybit_client` stale reference 버그 수정**: `from app.config import bybit_client` 형태로 값을 복사해오던 여러 서비스 모듈(`order_service.py`, `wallet_service.py`, `coin_service.py`, `price_service.py`)이, 웹UI에서 API 키를 나중에 저장해도 그 갱신을 못 받아오던 문제. `from app import config` + `config.bybit_client` 형태로 전환해 항상 최신 값을 참조하도록 수정.
- **`JWT_SECRET` 하드코딩 폴백 제거**: 환경변수 미설정 시 조용히 기본값으로 동작하던 것을 제거하고, 미설정이면 서버 기동 자체를 막도록(`RuntimeError`) 변경. 동시에 프로젝트 자체 `secrets.env`가 실제로 로드되지 않던 경로 문제도 같이 수정. (`app/config.py`)

### 상태 저장 레이스 컨디션 수정
- **문제**: 2초마다 도는 백그라운드 가격 업데이트 루프와, 웹UI의 강제 매도(`/api/sell/<coin>`) 요청이 각각 별도로 `상태 읽기 → 수정 → 저장`을 수행하면서, 타이밍이 겹치면 방금 종료한 포지션을 백그라운드 루프가 다시 덮어써 "매도했는데 코인이 다시 뜨는" 증상 발생.
- **수정**: `app/utils/state.py`에 `state_transaction()` 컨텍스트 매니저 신규 추가 — 파일 락을 읽기~쓰기 전체 구간에 걸쳐 유지. 백그라운드 루프(`app/services/price_service.py`의 `update_prices()`)와 강제 매도(`app/routes/dashboard.py`의 `sell_coin()`) 양쪽 모두 이걸 사용하도록 교체.

### 지갑 시드 자동 재분배 기능 추가
- **문제**: 지갑 기반 복리 시스템에서 지갑마다 손익이 누적되다 보니, 같은 수익률이라도 지갑별 실제 수익 금액이 계속 벌어짐 (수익난 지갑은 시드가 커지고 손실난 지갑은 작아짐).
- **추가**: `rebalance_wallets_if_idle()` 함수를 `app/services/trading_service.py`에 추가. 모든 지갑이 유휴 상태(진행 중인 포지션 없음)가 된 시점에만 총시드를 지갑 개수만큼 균등하게 재분배. 지갑이 하나라도 사용 중이면 재분배하지 않고 보류. `close_trade()` 종료 시점마다 자동 체크되므로 자동매매/수동 강제매도 모두에 동일하게 적용됨.

### 레거시 매도 엔드포인트 제거
- **문제**: `app/routes/coins.py`의 `sell_position()` (`POST /api/coins/<coin>`)이 `close_trade()`를 거치지 않고 자체적으로 포지션을 종료 처리하고 있었음 — 라이브 모드에서 실제 청산 주문을 넣지 않고, 지갑을 비활성화하지 않고, `state_transaction()` 락도 없어서 사용될 경우 상태 불일치와 중복 포지션 위험이 있었음. 프론트엔드에서는 사용하지 않는 죽은 코드였으나 잠재적 위험 요소였음.
- **수정**: 해당 라우트/함수 삭제. 강제 매도는 `app/routes/dashboard.py`의 `/api/sell/<coin>` (`state_transaction()` + `close_trade()` 사용) 하나로 통일.

### 레버리지 실거래소 반영
- **문제**: 지갑의 `leverage` 값이 포지션 사이징 계산에만 쓰이고 Bybit 거래소에는 실제로 설정되지 않았음. 계정에 마지막으로 수동 설정된 레버리지와 봇이 가정하는 레버리지가 다르면 실제 마진/리스크가 계산과 어긋날 수 있었음.
- **수정**: `app/services/order_service.py`에 `set_leverage()` 추가 (Bybit `set_leverage` API 호출, `buyLeverage`/`sellLeverage` 동시 설정). `app/services/trading_service.py`의 `auto_trade()`에서 라이브 모드 진입 주문 직전에 호출하도록 연결. 설정 실패 시 진입 주문 자체를 취소해 레버리지 불일치 상태로 포지션이 열리는 것을 방지.

---

**참고**: 위 모든 변경사항은 서버 재시작 후 적용됨.
