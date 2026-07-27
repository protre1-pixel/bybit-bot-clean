"""Flask 앱 초기화 및 라우트 등록"""
import os
import logging
import threading
from flask import Flask, render_template, make_response
from app.config import JWT_SECRET, USERS_DIR

# 로거 설정
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Flask 앱 생성
def create_app():
    """Flask 앱 팩토리"""
    # 절대 경로로 templates 폴더 지정
    template_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')
    app = Flask(__name__, template_folder=template_dir)

    # 설정
    app.config['SECRET_KEY'] = JWT_SECRET
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

    # 메인 페이지 라우트
    @app.route('/')
    def index():
        """메인 페이지"""
        response = make_response(render_template('index.html'))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    @app.route('/login')
    @app.route('/login.html')
    def login_page():
        """로그인 페이지"""
        response = make_response(render_template('login.html'))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    # 라우트 블루프린트 등록
    from app.routes import (
        auth_bp,
        dashboard_bp,
        trading_bp,
        coins_bp,
        settings_bp
    )

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(trading_bp)
    app.register_blueprint(coins_bp)
    app.register_blueprint(settings_bp)

    # Flask 로그 비활성화
    flask_log = logging.getLogger('werkzeug')
    flask_log.setLevel(logging.ERROR)

    logger.info("[INIT] Bybit Bot 시작 - 사용자 로그인 대기 중")

    return app


app = create_app()


def start_background_thread():
    """백그라운드 가격 업데이트 스레드 시작"""
    from app.services import update_prices
    thread = threading.Thread(target=update_prices, daemon=True)
    thread.start()
    logger.info("[INIT] 백그라운드 스레드 시작됨")
