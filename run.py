"""Bybit Bot 메인 실행 파일"""
import logging
import os

# 로거 설정
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

if __name__ == '__main__':
    # Flask 앱 및 백그라운드 스레드 시작
    from app import app, start_background_thread

    # 백그라운드 스레드 시작
    start_background_thread()

    # Flask 서버 시작
    port = int(os.getenv('PORT', 5300))
    logger.info("[INIT] Flask 서버 시작...")
    app.run(debug=False, host='0.0.0.0', port=port, threaded=True)
