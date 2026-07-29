# Bybit Margin Trading Bot

자동 거래 시스템 | ATR 기반 전략

## 설치 방법

### 1. 서버에 업로드
```
bybit-margin-bot/
├── app.py
├── templates/
│   └── index.html
├── requirements.txt
└── trades.json (자동 생성)
```

### 2. Python 의존성 설치
```bash
pip install -r requirements.txt
```

### 3. 앱 실행
```bash
python app.py
```

### 4. 브라우저 접속
```
http://localhost:5000
```

또는 서버 IP를 사용:
```
http://YOUR_SERVER_IP:5000
```

## 기능

### 📊 대시보드
- 실시간 BTC/ETH 가격
- 포지션 상태 모니터링
- 수익/손실 실시간 계산
- 통계 및 통계 정보

### 🤖 자동 거래
- ATR 기반 진입 신호
- TP 2% / SL 1.5% 자동 체크
- 10배 레버리지
- 75% 포지션 사이징

### 📄 페이퍼 모드
- "📄 페이퍼 모드" 버튼으로 시작
- 실제 돈 없이 시뮬레이션

### 📋 거래 기록
- 모든 거래 자동 기록
- 수익률, 거래 시간 저장
- JSON 포맷 (trades.json)

### 💰 강제 매도
- "매도" 버튼으로 즉시 종료
- 현재 가격으로 매도
- 수익 정산 자동

## 설정

### app.py 수정 가능 항목

```python
# 포트 변경
app.run(debug=True, host='0.0.0.0', port=5000)

# 초기 마진
state["btc"]["margin"] = 1000
state["eth"]["margin"] = 1000

# 레버리지
state["btc"]["leverage"] = 10
state["eth"]["leverage"] = 10

# TP/SL (auto_trade 함수에서 수정)
tp_price = state[coin_key]["entry_price"] * 1.02  # 2%
sl_price = state[coin_key]["entry_price"] * 0.985  # 1.5%
```

## API 엔드포인트

```
GET  /api/status          - 현재 상태
GET  /api/trades          - 거래 기록
GET  /api/stats           - 통계
GET  /api/mode            - 현재 모드
POST /api/mode/paper      - 페이퍼 모드 시작
POST /api/mode/live       - 라이브 모드 (준비 중)
POST /api/sell/<coin>     - 포지션 매도
POST /api/reset           - 상태 초기화
```

## 배포 옵션

### Gunicorn 사용 (프로덕션)
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

### Docker 사용
```dockerfile
FROM python:3.9
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "app.py"]
```

## 주의사항

⚠️ **현재는 페이퍼 모드만 지원**
- 실제 거래는 아직 구현되지 않음
- 시뮬레이션 목적으로만 사용

⚠️ **데이터 백업**
- trades.json은 중요한 거래 기록
- 정기적으로 백업하세요

⚠️ **API 키 관리**
- Bybit API는 아직 미통합
- 향후 구현 예정

## 지원

문제 발생 시:
1. 브라우저 콘솔(F12) 확인
2. 서버 로그 확인
3. requirements.txt 의존성 재설치

---

**개발자:** Claude Code
**마지막 업데이트:** 2026-07-22
