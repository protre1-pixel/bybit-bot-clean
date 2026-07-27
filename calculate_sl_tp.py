#!/usr/bin/env python3
"""기존 포지션의 SL/TP 자동 계산 설정"""
import json
import os

USERS_DIR = "users"

def calculate_sl_tp(coin_data):
    """기존 포지션의 SL/TP 계산"""
    if coin_data["position"] is None:
        return coin_data

    entry_price = coin_data.get("entry_price", 0)
    tp_percent = coin_data.get("tp", 2.0) / 100
    sl_percent = coin_data.get("sl", 1.5) / 100

    if entry_price == 0:
        return coin_data

    # SL/TP 계산
    if coin_data["position"] == "long":
        coin_data["tp_price"] = entry_price * (1 + tp_percent)
        coin_data["sl_price"] = entry_price * (1 - sl_percent)
    elif coin_data["position"] == "short":
        coin_data["tp_price"] = entry_price * (1 - tp_percent)
        coin_data["sl_price"] = entry_price * (1 + sl_percent)

    return coin_data

def upgrade_user_state(filepath):
    """사용자 state 파일 업그레이드 (SL/TP 계산)"""
    try:
        with open(filepath, 'r') as f:
            state = json.load(f)

        updated = False
        for key in state:
            if key not in ["mode", "coins", "total_seed", "coin_settings"]:
                if isinstance(state[key], dict) and "position" in state[key]:
                    state[key] = calculate_sl_tp(state[key])
                    updated = True

        if updated:
            with open(filepath, 'w') as f:
                json.dump(state, f, indent=2)
            return True
        return False
    except Exception as e:
        print(f"❌ 실패: {filepath} - {e}")
        return False

def main():
    if not os.path.exists(USERS_DIR):
        print("❌ users 디렉토리 없음")
        return

    upgraded = 0
    for username in os.listdir(USERS_DIR):
        user_dir = os.path.join(USERS_DIR, username)
        if not os.path.isdir(user_dir):
            continue

        state_file = os.path.join(user_dir, "bot_state.json")
        if os.path.exists(state_file):
            if upgrade_user_state(state_file):
                print(f"✅ SL/TP 설정 완료: {username}")
                upgraded += 1

    print(f"\n🎉 총 {upgraded}개 사용자의 기존 포지션 SL/TP 계산 완료!")

if __name__ == "__main__":
    main()
