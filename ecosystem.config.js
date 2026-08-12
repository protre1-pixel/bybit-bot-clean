module.exports = {
  apps: [
    {
      name: 'bybit-bot2',
      script: 'run.py',
      interpreter: 'python3',  // 서버에 맞게 'python' 또는 'python3'
      interpreter_args: '-u',  // Python 버퍼링 제거 (로그를 즉시 출력)
      env: {
        FLASK_ENV: 'production',
        PORT: 5400
      },
      instances: 1,
      exec_mode: 'fork',
      max_memory_restart: '500M',
      autorestart: true,
      watch: false,
      ignore_watch: ['logs', 'node_modules', '__pycache__', '*.pyc', 'selected_coins_cache.json'],
      merge_logs: true,
      output: './logs/out.log',
      error: './logs/error.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z'
    }
  ]
};
