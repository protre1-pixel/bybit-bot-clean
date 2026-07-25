# bybit-bot-clean

**Multi-user Web-based Cryptocurrency Trading Bot with Strategy V2**

## 📋 개요

- **목적**: 실시간 암호화폐 거래 봇 (웹 기반 대시보드)
- **전략**: Strategy V2 (복합 조건 기반)
- **특징**: 멀티 사용자 지원, 실시간 거래 추적
- **포트**: 5000 (로컬 테스트용)
- **서버**: 192.168.1.134:5000

## 🗂️ 폴더 구조

```
bybit-bot-clean/
├── app.py                 # Flask 메인 애플리케이션
├── index.html            # 메인 대시보드 (HTML)
├── login.html            # 로그인 페이지
├── templates/            # HTML 템플릿
│   ├── index.html
│   └── login.html
├── users/                # 사용자별 거래 데이터
│   ├── protre/
│   ├── guest/
│   └── testuser*/
├── bot_state.json        # 봇 상태 저장
├── trades.json           # 거래 기록
├── settings.json         # 봇 설정
├── requirements.txt      # Python 의존성
└── .git/                 # Git 저장소
```

## 🚀 실행 방법

### 로컬 실행
```bash
cd C:\Users\protre\Desktop\bybit-bot-clean
python app.py
```

### 서버 실행 (PM2)
```bash
# SSH로 접속
ssh protre@192.168.1.134

# 상태 확인
pm2 list | grep bybit-bot-clean

# 로그 확인
pm2 logs bybit-bot-clean

# 재시작
pm2 restart bybit-bot-clean
```

## 📊 주요 기능

### 1. 실시간 거래
- 멀티 코인 지원
- 자동 거래 신호 생성
- Long/Short 포지션 지원
- 거래 기록 자동 저장

### 2. 웹 대시보드
- 실시간 거래 상태 모니터링
- 거래 기록 조회
- 통계 및 분석
- 멀티 사용자 관리

### 3. 사용자 관리
- 사용자별 독립적인 거래 기록
- 사용자별 설정 저장
- 로그인 기능

## 💾 데이터 저장

### 거래 기록
- **파일**: `users/{username}/trades.json`
- **형식**: JSON
- **저장**: 거래 시마다 자동 저장

### 봇 상태
- **파일**: `users/{username}/bot_state.json`
- **형식**: JSON
- **저장**: 상태 변경 시 자동 저장

## 🔧 설정

### settings.json
```json
{
  "leverage": 10,
  "tp_pct": 2.0,
  "sl_pct": 1.5,
  "position_size_ratio": 0.75
}
```

## 🔌 API 엔드포인트

### 거래 관련
- `POST /api/trade` - 거래 시작
- `POST /api/close_position` - 포지션 종료
- `POST /api/force_sell` - 강제 매도
- `GET /api/trades` - 거래 기록 조회

### 통계 관련
- `GET /api/stats` - 통계 조회
- `GET /api/daily_profit/<date>` - 일별 수익

### 설정 관련
- `GET /api/settings` - 설정 조회
- `POST /api/settings` - 설정 변경

## 📝 커밋 이력

최근 커밋:
```
4ba4fc4 - feat: Add exit time display in trade history table
```

## ⚠️ 주의사항

1. **포트 충돌**: 포트 5000이 사용 중이면 변경 필요
2. **데이터 백업**: 정기적으로 거래 데이터 백업
3. **API 키**: secrets.env 파일에서 관리

## 🔄 서버와 동기화

### 로컬 → 서버
```bash
# 파일 업로드
scp -r C:\Users\protre\Desktop\bybit-bot-clean\* protre@192.168.1.134:/home/protre/bybit-bot-clean/

# PM2 재시작
ssh protre@192.168.1.134 "pm2 restart bybit-bot-clean"
```

### 서버 → 로컬 (데이터 받기)
```bash
# 거래 데이터 다운로드
scp -r protre@192.168.1.134:/home/protre/bybit-bot-clean/users C:\Users\protre\Desktop\bybit-bot-clean\
```

## 🐛 문제 해결

### 포트 에러
```
Address already in use
```
→ 포트 변경: `app.py`의 `app.run(port=XXXX)` 수정

### 데이터 손실
```
trades.json 없음
```
→ 백업에서 복구: `users/{username}/trades.json.bak`

## 📞 연락처

유저명: protre
서버: 192.168.1.134

---

**마지막 업데이트**: 2026-07-25
**상태**: 운영 중
