#!/usr/bin/env python3
"""기존 state 파일을 업그레이드 (SL/TP 필드 추가)"""
import json
import os
from pathlib import Path

USERS_DIR = "users"

def upgrade_coin_state(coin_data):
    """코인 상태에 SL/TP 필드 추가"""
    # 이미 필드가 있으면 그대로 두기
    if "sl_price" not in coin_data:
        coin_data["sl_price"] = None
    if "tp_price" not in coin_data:
        coin_data["tp_price"] = None
    if "min_profit_price" not in coin_data:
        coin_data["min_profit_price"] = None
    return coin_data

def upgrade_user_state(filepath):
    """사용자 state 파일 업그레이드"""
    try:
        with open(filepath, 'r') as f:
            state = json.load(f)

        # 각 코인별 상태 업그레이드
        for key in state:
            if key not in ["mode", "coins", "total_seed", "coin_settings"]:
                if isinstance(state[key], dict) and "position" in state[key]:
                    state[key] = upgrade_coin_state(state[key])

        # coin_settings 필드 추가
        if "coin_settings" not in state:
            state["coin_settings"] = {}

        # 파일 저장
        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2)

        print(f"✅ 업그레이드 완료: {filepath}")
        return True
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
                upgraded += 1

    print(f"\n🎉 총 {upgraded}개 사용자 파일 업그레이드 완료!")

if __name__ == "__main__":
    main()
