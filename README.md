# Bybit Bot

볼린저밴드 Squeeze/Breakout 전략 기반 멀티유저 웹 자동매매 봇 (Flask).

## 구조

```
bybit-bot/
├── run.py                     # 실행 진입점 (Flask 서버 + 백그라운드 가격 스레드)
├── secrets.env                # BYBIT_API_KEY/SECRET, JWT_SECRET 등 (git에 커밋 금지)
├── requirements.txt
├── templates/
│   ├── index.html             # 대시보드
│   └── login.html             # 로그인
├── users/                     # 사용자별 데이터 (자동 생성)
│   └── <username>/
│       ├── bot_state.json     # 코인별 포지션/지갑 상태
│       └── trades.json        # 거래 기록
└── app/
    ├── __init__.py            # Flask 앱 팩토리, 블루프린트 등록
    ├── config.py               # secrets.env 로드, JWT/Bybit 클라이언트 초기화
    ├── routes/                 # HTTP 엔드포인트 (블루프린트)
    │   ├── auth.py             # 회원가입/로그인
    │   ├── dashboard.py        # 상태/통계/거래기록/강제매도
    │   ├── trading.py          # 자동매매 시작/중지/리셋
    │   ├── coins.py            # 코인 추가/제거/개별 설정
    │   └── settings.py         # 전역 설정(시드, 거래건수), 지갑 설정
    ├── services/                # 비즈니스 로직
    │   ├── auth_service.py
    │   ├── coin_service.py      # 거래 가능 코인 자동 선별
    │   ├── price_service.py     # 백그라운드 가격 업데이트 루프, BB 계산
    │   ├── trading_service.py   # 진입/청산 로직, TP/SL, 지갑 재분배
    │   ├── order_service.py     # Bybit 실주문 (수량 반올림, reduceOnly)
    │   └── wallet_service.py    # Bybit 실잔고 조회/검증
    └── utils/
        ├── decorators.py        # @token_required (JWT 인증)
        ├── state.py              # 상태 파일 로드/저장, state_transaction (락 기반 트랜잭션)
        └── helpers.py
```

## 실행 방법

### 1. 의존성 설치
```bash
pip install -r requirements.txt
```

### 2. `secrets.env` 준비 (프로젝트 루트)
```
BYBIT_API_KEY=...
BYBIT_API_SECRET=...
JWT_SECRET=...          # 32바이트 이상 랜덤 값 권장
FLASK_ENV=production
PORT=5300
```
API 키가 없으면 `bybit_client`가 `None`으로 초기화되고, 라이브 주문 없이 페이퍼 모드로만 동작함.

### 3. 서버 실행
```bash
python run.py
```
기본 포트는 `5300` (환경변수 `PORT`로 변경 가능). 브라우저에서 `http://localhost:5300` 접속.

### 4. PM2로 상시 구동 (서버 배포 시)
```bash
pm2 start run.py --name bybit-bot --interpreter python
pm2 logs bybit-bot
pm2 restart bybit-bot
```

## 전략 개요

- **신호**: 1분봉 기준 볼린저밴드 폭이 평균 대비 50% 이하로 좁아졌다가(Squeeze), 평균 이상으로 확 넓어지는 순간(Breakout) 진입. 확장이 확인된 캔들의 몸통 방향(양봉=롱, 음봉=숏)으로 포지션 진입.
- **TP/SL (Normal 모드)**: 진입 후 가격이 유리한 방향으로 새로운 고점/저점을 갱신할 때만 볼린저밴드 폭 기반으로 SL/TP를 재계산해 트레일링. 가격이 정체되거나 불리하게 움직이면 SL/TP를 유지 (밴드 폭 수축만으로 SL이 타이트해지지 않도록 방지).
- **TP/SL (Trailing 모드)**: 미실현 수익 5% 이상 도달 시 단순 2% 트레일링 스탑으로 전환.
- **재진입 제한**: 포지션 종료 후 5분간 같은 코인 자동 재진입 금지.

## 지갑 기반 복리 시스템

- 전역 설정에서 총시드(`total_seed`)와 동시 거래 허용 건수(`max_trades`)를 정하면, 총시드를 균등 분할한 지갑(`wallet_1`, `wallet_2`, ...)이 생성됨.
- 진입 시 비어있는 지갑을 하나 배정받아 그 지갑의 `current_seed` 기준으로 포지션 사이징. 청산 시 손익이 해당 지갑의 `current_seed`에 누적됨.
- **자동 재분배**: 지갑별로 손익이 누적되다 보면 같은 수익률이라도 지갑마다 실제 금액이 벌어지는데, **모든 지갑이 유휴 상태(진행 중인 포지션 0건)가 되는 시점마다** 총시드를 지갑 개수로 나눠 각 지갑의 `current_seed`를 균등하게 재분배함. 하나라도 거래 중인 지갑이 있으면 재분배는 보류됨. (`trading_service.rebalance_wallets_if_idle`)

## 모드

- **paper**: 실제 주문 없이 시뮬레이션. 기본값.
- **live**: Bybit 실주문 (`reduceOnly`로 청산 안전성 확보, 심볼별 `qtyStep`/`minOrderQty`에 맞춰 수량 반올림).

`POST /api/mode/<paper|live>` 로 전환.

## 동시성/안전성

- 상태 파일(`bot_state.json`)은 사용자별 파일 락으로 보호되며, `state_transaction()` 컨텍스트 매니저가 "읽기→수정→저장" 전체를 하나의 락으로 묶어 백그라운드 가격 업데이트 루프(2초 주기)와 강제 매도 같은 요청 핸들러 사이의 레이스 컨디션을 방지함.

## API 엔드포인트

### 인증 (`/api/auth`)
```
POST /api/auth/register    - 회원가입
POST /api/auth/login       - 로그인 (JWT 발급)
POST /api/auth/logout      - 로그아웃
GET  /api/auth/check       - 로그인 상태 확인
```

### 대시보드 (`/api`)
```
GET  /api/status                    - 전체 코인 상태, 지갑, 총수익
GET  /api/trades                    - 거래 기록 전체
GET  /api/stats                     - 승률/평균수익 등 통계
GET  /api/mode                      - 현재 모드(paper/live)
POST /api/mode/<mode>               - 모드 전환
GET  /api/calendar/<year>/<month>   - 달력용 일별 수익 데이터
GET  /api/trades/<date>             - 특정 날짜 거래 내역
GET  /api/wallet/balance            - Bybit 실제 USDT 잔액 조회
POST /api/wallet/validate           - UI 초기자본 vs 실제 잔고 검증
POST /api/sell/<coin>               - 강제 매도 (즉시 포지션 종료)
```

### 자동매매 (`/api/trading`)
```
POST /api/trading/start    - 자동매매 시작
POST /api/trading/stop     - 자동매매 중지
GET  /api/trading/status   - 자동매매 on/off 상태
POST /api/trading/reset    - 상태 초기화
```

### 코인 (`/api/coins`)
```
GET  /api/coins                    - 현재 선택된 코인 목록
GET  /api/coins/list                - 거래 가능 전체 코인 목록
POST /api/coins/add                 - 코인 추가
POST /api/coins/remove               - 코인 제거
GET  /api/coins/<coin>/settings      - 코인별 설정 조회
POST /api/coins/<coin>/settings      - 코인별 설정 변경
```

### 설정 (`/api`)
```
GET  /api/settings                  - 전체 설정 조회
GET  /api/settings/<coin>           - 코인별 설정 조회
POST /api/settings/<coin>           - 코인별 설정 변경
GET  /api/global-settings           - 전역 설정(총시드/거래건수) 조회
POST /api/global-settings           - 전역 설정 변경 (총시드/거래건수 변경 시 지갑 재분배)
POST /api/user/settings/api         - Bybit API 키 저장 (실시간 반영)
```

## 주의사항

⚠️ **API 키 관리**: `secrets.env`는 절대 git에 커밋하지 말 것. 유출 시 즉시 Bybit에서 키 폐기/재발급.

⚠️ **라이브 모드**: 실제 자금이 오가는 모드이므로, 같은 계정의 봇 프로세스가 여러 대(로컬+서버 등)에서 동시에 돌지 않도록 주의. 중복 실행 시 상태 파일 충돌 및 중복 주문 위험.

⚠️ **데이터 백업**: `users/<username>/trades.json`, `bot_state.json`은 정기적으로 백업 권장.

세부 변경 이력은 [CHANGELOG.md](CHANGELOG.md) 참고.

---

**마지막 업데이트**: 2026-08-04
