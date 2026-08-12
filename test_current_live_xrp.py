# -*- coding: utf-8 -*-
# 2026-08-07: app/services/trading_service.py의 "현재" 라이브 로직을 최대한 그대로
# 재현해서 XRP 백테스트. 이전 backtest_bb_squeeze.py의 run_backtest()는 구버전(ADX 필터,
# 1h HTF, 퍼센트 기반 breakeven/partial_lock/trailing 4단계)이라 지금 라이브와 안 맞음.
#
# 재현 대상(현재 라이브 상태):
#   진입: Squeeze Breakout(구간 최저점*1.5) + 15분봉 HMA200/600 정배열 필터 (ADX 없음)
#   초기 SL/TP: avg_width(BB 30봉 평균폭) 기준, SL 상한 = min(sl_percent=3%, (1/lev)*0.8)
#   0단계 normal: 신고점마다 avg_width로 SL/TP 갱신(TP도 계속 따라감)
#   1단계 trend_follow: 최고수익 1% 도달 시 전환. 먼저 SL을 본전+수수료(0.15%)로 최소방어.
#     이후 15분봉 HMA200/600 갭(부호있는 fast-slow)을 추적:
#       - 갭 부호가 반전(추세완전반전) → 즉시 전량 청산
#       - 갭이 진입 이후 최댓값 대비 60% 밑으로 수축 → SL을 현재가 근처(0.3%)로 타이트닝
#       - TP 없음, SL만으로 청산판정
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np
import backtest_bb_squeeze as bt

SYMBOL = sys.argv[1].upper() if len(sys.argv) > 1 else "XRPUSDT"
DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 120
# 2026-08-07: 사용자 요청 - "1분봉으로 지금조건 똑같이" 실험. 캔들 단위 파라미터(BB
# lookback=30, HMA200/600 등)는 그대로 두고 기준 타임프레임만 15분 -> 1분으로 바꿔서
# 비교(주의: HMA200/600도 "1분×200/600" = 3.3시간/10시간 lookback으로 의미가 바뀜).
_interval_arg = next((a for a in sys.argv if a.startswith("--interval=")), None)
INTERVAL = _interval_arg.split("=")[1] if _interval_arg else "15"
# 2026-08-07: 사용자 요청 - "sl 3%로 고정" 실험. 기존은 min(avg_width, 3%)로 avg_width가
# 좁으면 그보다 타이트하게 걸렸는데, 이걸 끄고 항상 3% 그대로 쓰도록 하는 옵션.
FIXED_SL = "--fixed-sl" in sys.argv
# 2026-08-07: 사용자 요청 - "SL을 없게" 실험. 0단계 SL 체크(진입시 avg_width/3% 캡)와
# 1단계(trend_follow)의 staged SL(본전방어+수축시타이트닝)을 전부 끔. 단, "갭 부호 반전
# (추세 완전반전) 즉시청산"은 SL가 아니라 별개의 하드 룰이라 그대로 둠. 그리고 거래소
# 강제청산(마진콜)은 봇 설정과 무관하게 실제로 일어나는 일이라 항상 시뮬레이션함
# (10x 레버리지 기준 이론상 청산선 ≈ (1/lev)-유지증거금율 ≈ 9.5%).
NO_SL = "--no-sl" in sys.argv
LIQUIDATION_PCT = 0.095
# 2026-08-07: 사용자 요청 - "BB 밴드 길이 30 → 20" 실험. calculate_band_width_average()의
# lookback(=BB 폭 계산에 쓰는 캔들 개수)을 30에서 20으로 줄여서 스퀴즈/브레이크아웃 판정과
# avg_width 기반 SL/TP 산정이 더 짧은 구간 기준으로 빠르게 반응하게 만드는 실험.
BB20 = "--bb20" in sys.argv
# 2026-08-07: 사용자 요청 - "Stop Loss 24→42건으로 늘어난 문제(BB20) / 즉시반전형
# fakeout 손절이 절반" 진단 후, 레버1(확인캔들) 실험. 브레이크아웃이 뜬 캔들에서 바로
# 진입하지 않고, "다음 캔들에도 여전히 브레이크아웃 상태(같은 임계값 유지)+같은 방향"일
# 때만 그 다음 캔들 종가로 진입. 단순 위꼬리/아래꼬리성 노이즈 돌파를 1개 캔들(15분)
# 지연시켜 걸러내는 목적.
CONFIRM = "--confirm" in sys.argv
# 2026-08-07: 사용자 요청 - "진입할 때 거래량도 보나?" -> 지금은 안 봄(확인 결과 라이브
# 코드에 거래량 필터 없음). 브레이크아웃 캔들(idx_prev, direction 판정에 쓰는 그 캔들)의
# 거래량이 직전 VOL_LOOKBACK개 평균 대비 VOL_MULT배 이상일 때만 신호를 인정하는 필터를
# 추가해서 실험. --vol=1.5 처럼 배수 지정, 없으면 필터 비활성(None).
_vol_arg = next((a for a in sys.argv if a.startswith("--vol=")), None)
VOL_MULT = float(_vol_arg.split("=")[1]) if _vol_arg else None
VOL_LOOKBACK = 20
# 2026-08-07: 사용자 요청 - "HMA200/600 정배열" 대신 "HMA200 하나만" 진입필터로 써보기.
# 롱: 가격이 HMA200 위, 숏: 가격이 HMA200 아래일 때만 통과.
SINGLE_HMA = "--single-hma" in sys.argv
# 2026-08-07 3차 수정: BB상단/하단밴드 정배열 아이디어는 폐기(신호 무의미 확인됨).
# 대신: 진입필터는 SINGLE_HMA와 동일(가격 vs HMA200)로 하고, 진입 후에는
#   - 0단계(normal): 가격이 HMA200 유리한 쪽에 있는 동안만 유지, 반대로 넘어가면 즉시청산.
#   - HMA200/600이 정배열(기존 방식과 동일한 gap_at 기준)로 놓이면 그 시점부터 1단계
#     (trend_follow)로 전환 - 기존 "최고수익 1%" 트리거 대신 이 정배열 트리거를 씀.
#   - 1단계 진입 후는 기존 로직(gap 부호반전 즉시청산 + 수축시 SL 타이트닝) 그대로 재사용.
HMA_FOLLOW = "--hma-follow" in sys.argv

BB_PERIOD = 30
WIDTH_LOOKBACK = 20 if BB20 else 30
WIDTH_FETCH_WINDOW = 100
SQUEEZE_ENTER_MULT = 0.5
# 2026-08-07: 사용자 요청 - 레버2(돌파배수 상향) 실험. --mult=1.8 처럼 커맨드라인으로
# 오버라이드 가능하게. 기본값은 기존과 동일한 1.5.
_mult_arg = next((a for a in sys.argv if a.startswith("--mult=")), None)
BREAKOUT_MULT = float(_mult_arg.split("=")[1]) if _mult_arg else 1.5

ENTRY_PERCENT = 0.75
LEVERAGE = 10
SEED = 1000.0
FEE_RATE = 0.00055
NORMAL_SL_MULT = 0.8
REENTRY_COOLDOWN_SEC = 300  # 라이브 실제값(auto_trade 상단, 30분 아니고 5분)

# 2026-08-07: 사용자 요청 - 라이브 로그에서 HEI가 BB폭 기반 SL(29.54%)이 안전상한(1.50%,
# 그 지갑의 sl%가 구설정 1.5%로 남아있던 경우)에 눌려서 거의 즉시 SL 맞은 사례 확인 후,
# "상한을 5%로 걸어두면 어떨까" 실험. --slcap=0.05 처럼 오버라이드.
_slcap_arg = next((a for a in sys.argv if a.startswith("--slcap=")), None)
SL_PERCENT = float(_slcap_arg.split("=")[1]) if _slcap_arg else 0.03
STAGE1_TRIGGER_PCT = 1.0
STAGE1_FEE_BUFFER_PCT = 0.15

HMA_FAST = 200
HMA_SLOW = 600
HMA_CONTRACTION_RATIO = 0.6
HMA_EXIT_BUFFER_PCT = 0.3


def hma_series(values, period):
    half = period // 2
    sq = int(np.sqrt(period))
    wma1 = bt.wma(values, half)
    wma2 = bt.wma(values, period)
    diff = 2 * wma1 - wma2
    return bt.wma(diff, sq)


def sma_series(values, period):
    n = len(values)
    out = np.full(n, np.nan)
    csum = np.cumsum(np.insert(values, 0, 0.0))
    for i in range(period - 1, n):
        out[i] = (csum[i + 1] - csum[i + 1 - period]) / period
    return out


def ema_series(values, period):
    n = len(values)
    out = np.full(n, np.nan)
    if n < period:
        return out
    alpha = 2 / (period + 1)
    seed = np.mean(values[:period])
    out[period - 1] = seed
    prev = seed
    for i in range(period, n):
        prev = values[i] * alpha + prev * (1 - alpha)
        out[i] = prev
    return out


# 2026-08-07: 사용자 요청 - "SMA/EMA/MA/HMA 중 신호가 가장 괜찮은 게 뭘까?" 실험.
# HTF 진입필터 + 청산단계(trend_follow)의 갭 추적에 둘 다 쓰는 이동평균 종류를
# --matype=hma(기본)|sma|ema|wma 로 바꿔서 비교.
_matype_arg = next((a for a in sys.argv if a.startswith("--matype=")), None)
MA_TYPE = _matype_arg.split("=")[1] if _matype_arg else "hma"

MA_SERIES_FN = {
    "hma": hma_series,
    "sma": sma_series,
    "ema": ema_series,
    "wma": bt.wma,
}[MA_TYPE]


def run(candles):
    close = np.array([c["close"] for c in candles])
    print(f"{MA_TYPE.upper()}200/600 사전계산 중...")
    hma_fast = MA_SERIES_FN(close, HMA_FAST)
    hma_slow = MA_SERIES_FN(close, HMA_SLOW)

    def htf_at(idx):
        if idx < 0 or idx >= len(hma_fast):
            return None
        if SINGLE_HMA or HMA_FOLLOW:
            # HMA200 하나만: 가격이 그 위/아래인지만 본다 (HMA600 정배열 대신)
            f = hma_fast[idx]
            price = close[idx]
            if np.isnan(f):
                return None
            if price > f:
                return "up"
            elif price < f:
                return "down"
            return None
        f, s = hma_fast[idx], hma_slow[idx]
        if np.isnan(f) or np.isnan(s):
            return None
        if f > s:
            return "up"
        elif f < s:
            return "down"
        return None

    def volume_ok(idx):
        """idx 캔들(브레이크아웃 방향 판정에 쓰인 캔들)의 거래량이 직전 VOL_LOOKBACK개
        평균 거래량 대비 VOL_MULT배 이상이면 True. 데이터 부족/필터 비활성 시 통과."""
        if VOL_MULT is None:
            return True
        lo = max(0, idx - VOL_LOOKBACK)
        window = candles[lo:idx]
        if len(window) < VOL_LOOKBACK:
            return True
        avg_vol = sum(x["volume"] for x in window) / len(window)
        if avg_vol <= 0:
            return True
        return candles[idx]["volume"] >= avg_vol * VOL_MULT

    def gap_at(idx):
        if idx < 0 or idx >= len(hma_fast):
            return None
        f, s = hma_fast[idx], hma_slow[idx]
        if np.isnan(f) or np.isnan(s):
            return None
        return f - s

    seed = SEED
    position = None
    trades = []
    squeeze_status = "normal"
    squeeze_width = None
    last_close_ts = None
    pending = None  # CONFIRM 모드에서 "확인 대기 중" 브레이크아웃 {"side", "threshold"}

    min_start = max(WIDTH_FETCH_WINDOW + WIDTH_LOOKBACK + 5, HMA_SLOW + 5)

    for t in range(min_start, len(candles)):
        c = candles[t]
        idx_prev = t - 1  # bt.py 컨벤션: "마지막 완성 캔들" = t-1

        # ---- 포지션 관리 ----
        if position:
            price_high, price_low = c["high"], c["low"]
            side = position["side"]
            sl_hit = tp_hit = False
            exit_price = None
            reason = None

            # ── 거래소 강제청산(마진콜) - SL 유무와 무관하게 항상 시뮬레이션 ──
            liq_price = (position["entry"] * (1 - LIQUIDATION_PCT) if side == "long"
                         else position["entry"] * (1 + LIQUIDATION_PCT))
            if (side == "long" and price_low <= liq_price) or (side == "short" and price_high >= liq_price):
                sl_hit, exit_price, reason = True, liq_price, "Liquidation"

            # ── HMA_FOLLOW: 0단계(normal) 동안은 가격이 HMA200 유리한 쪽에 있는지만
            # 감시 - 반대로 넘어가면 SL/TP 판정과 무관하게 즉시 청산(하드 룰) ──
            if not sl_hit and HMA_FOLLOW and position["profit_mode"] == "normal":
                f200 = hma_fast[idx_prev] if 0 <= idx_prev < len(hma_fast) else np.nan
                if not np.isnan(f200):
                    broke = (c["close"] < f200) if side == "long" else (c["close"] > f200)
                    if broke:
                        sl_hit, exit_price, reason = True, c["close"], "HMA200 Break"

            old_max = position["max_profit_price"]
            if side == "long":
                if price_high > old_max:
                    position["max_profit_price"] = price_high
            else:
                if price_low < old_max:
                    position["max_profit_price"] = price_low
            is_new_high = position["max_profit_price"] != old_max

            if side == "long":
                peak_profit_pct = (position["max_profit_price"] - position["entry"]) / position["entry"] * 100
            else:
                peak_profit_pct = (position["entry"] - position["max_profit_price"]) / position["entry"] * 100

            # ── 단계 전환 (한번 올라가면 안 내려감) ──
            # HMA_FOLLOW: 기존 "최고수익 1%" 트리거 대신 "HMA200/600 정배열"이 트리거.
            if position["profit_mode"] == "normal":
                if HMA_FOLLOW:
                    stage_gap = gap_at(idx_prev)
                    stage_favorable = stage_gap is not None and (
                        (stage_gap > 0) if side == "long" else (stage_gap < 0))
                    if stage_favorable:
                        position["profit_mode"] = "trend_follow"
                        position["hma_gap_peak"] = 0.0
                elif peak_profit_pct >= STAGE1_TRIGGER_PCT:
                    position["profit_mode"] = "trend_follow"
                    position["hma_gap_peak"] = 0.0

            staged_sl = None
            if not sl_hit and position["profit_mode"] == "trend_follow":
                if not NO_SL:
                    staged_sl = (position["entry"] * (1 + STAGE1_FEE_BUFFER_PCT / 100) if side == "long"
                                 else position["entry"] * (1 - STAGE1_FEE_BUFFER_PCT / 100))

                gap = gap_at(idx_prev)
                if gap is not None:
                    favorable = (gap > 0) if side == "long" else (gap < 0)
                    if not favorable:
                        # 추세 완전반전 - NO_SL이어도 이건 SL이 아니라 별개의 하드 룰이라 유지
                        sl_hit, exit_price, reason = True, c["close"], "HMA Trend Reversal"
                    elif not NO_SL:
                        gap_abs = abs(gap)
                        gap_peak = max(position.get("hma_gap_peak", 0.0), gap_abs)
                        position["hma_gap_peak"] = gap_peak
                        if gap_peak > 0 and gap_abs < gap_peak * HMA_CONTRACTION_RATIO:
                            tight_sl = (c["close"] * (1 - HMA_EXIT_BUFFER_PCT / 100) if side == "long"
                                        else c["close"] * (1 + HMA_EXIT_BUFFER_PCT / 100))
                            staged_sl = max(staged_sl, tight_sl) if side == "long" else min(staged_sl, tight_sl)
                    else:
                        # NO_SL: 갭 최댓값 추적만 계속(나중에 재활성화 대비), 타이트닝은 안 함
                        gap_abs = abs(gap)
                        position["hma_gap_peak"] = max(position.get("hma_gap_peak", 0.0), gap_abs)

            if not sl_hit and staged_sl is not None:
                if side == "long" and staged_sl > position["sl_price"]:
                    position["sl_price"] = staged_sl
                elif side == "short" and staged_sl < position["sl_price"]:
                    position["sl_price"] = staged_sl

            if not sl_hit and position["profit_mode"] == "normal" and is_new_high:
                wi = bt.width_info_at(candles, t, lookback=WIDTH_LOOKBACK)
                w = wi["avg_width"] if wi else position["entry_bb_width"]
                if side == "long":
                    new_sl = position["max_profit_price"] - w * NORMAL_SL_MULT
                    if new_sl > position["sl_price"]:
                        position["sl_price"] = new_sl
                    new_tp = position["max_profit_price"] + w
                    if new_tp > position["tp_price"]:
                        position["tp_price"] = new_tp
                else:
                    new_sl = position["max_profit_price"] + w * NORMAL_SL_MULT
                    if new_sl < position["sl_price"]:
                        position["sl_price"] = new_sl
                    new_tp = position["max_profit_price"] - w
                    if new_tp < position["tp_price"]:
                        position["tp_price"] = new_tp

            if not sl_hit:
                if position["profit_mode"] == "normal":
                    if side == "long":
                        if not NO_SL and price_low <= position["sl_price"] and price_high >= position["tp_price"]:
                            sl_hit, exit_price, reason = True, position["sl_price"], "Stop Loss"
                        elif not NO_SL and price_low <= position["sl_price"]:
                            sl_hit, exit_price, reason = True, position["sl_price"], "Stop Loss"
                        elif price_high >= position["tp_price"]:
                            tp_hit, exit_price, reason = True, position["tp_price"], "Take Profit"
                    else:
                        if not NO_SL and price_high >= position["sl_price"] and price_low <= position["tp_price"]:
                            sl_hit, exit_price, reason = True, position["sl_price"], "Stop Loss"
                        elif not NO_SL and price_high >= position["sl_price"]:
                            sl_hit, exit_price, reason = True, position["sl_price"], "Stop Loss"
                        elif price_low <= position["tp_price"]:
                            tp_hit, exit_price, reason = True, position["tp_price"], "Take Profit"
                else:  # trend_follow, TP 없음
                    if not NO_SL:
                        if side == "long":
                            if price_low <= position["sl_price"]:
                                sl_hit, exit_price, reason = True, position["sl_price"], "Trend Follow Stop"
                        else:
                            if price_high >= position["sl_price"]:
                                sl_hit, exit_price, reason = True, position["sl_price"], "Trend Follow Stop"

            if sl_hit or tp_hit:
                pnl_pct = (exit_price - position["entry"]) / position["entry"]
                if side == "short":
                    pnl_pct = -pnl_pct
                nominal = seed * ENTRY_PERCENT * LEVERAGE
                gross = nominal * pnl_pct
                fees = nominal * FEE_RATE * 2
                net = gross - fees
                seed += net
                # 2026-08-07: 사용자 요청 - "매도는 내가 차트보면서 할꺼야, 진입만 잘하면돼"
                # -> 봇의 청산로직과 무관하게 "진입 후 도달했던 최고 평가수익률"(사람이 직접
                # 그 근처에서 팔았다면 얻었을 최대치)을 별도로 기록해서 진입 품질만 따로 평가.
                if side == "long":
                    peak_pct_final = (position["max_profit_price"] - position["entry"]) / position["entry"] * 100 * LEVERAGE
                else:
                    peak_pct_final = (position["entry"] - position["max_profit_price"]) / position["entry"] * 100 * LEVERAGE
                trades.append({
                    "side": side, "entry": position["entry"], "exit": exit_price,
                    "entry_ts": position["entry_ts"], "exit_ts": c["ts"],
                    "reason": reason, "profit": net, "profit_pct": pnl_pct * 100 * LEVERAGE,
                    "peak_pct": peak_pct_final,
                    "seed_after": seed
                })
                last_close_ts = c["ts"]
                position = None
                continue

        # ---- 신규 진입 체크 ----
        if not position:
            if last_close_ts is not None and (c["ts"] - last_close_ts) / 1000 < REENTRY_COOLDOWN_SEC:
                continue

            wi = bt.width_info_at(candles, t, lookback=WIDTH_LOOKBACK)
            if wi is None:
                pending = None
                continue
            cw, aw = wi["current_width"], wi["avg_width"]

            def try_enter(signal, aw=aw):
                """진입 필터 통과 시 position 오픈. 실패하면 None 반환."""
                trend = htf_at(idx_prev)
                trend_ok = (
                    (signal == "long" and trend == "up") or
                    (signal == "short" and trend == "down")
                )
                if not trend_ok:
                    return None

                entry_price = c["close"]
                bb_width = max(aw, entry_price * 0.002)
                leverage_safety_pct = (1 / LEVERAGE) * 0.8 if LEVERAGE > 0 else SL_PERCENT
                max_sl_distance_pct = min(SL_PERCENT, leverage_safety_pct)
                max_sl_distance = entry_price * max_sl_distance_pct
                sl_distance = max_sl_distance if FIXED_SL else min(bb_width, max_sl_distance)

                if signal == "long":
                    tp = entry_price + bb_width
                    sl = entry_price - sl_distance
                else:
                    tp = entry_price - bb_width
                    sl = entry_price + sl_distance

                return {
                    "side": signal, "entry": entry_price, "entry_ts": c["ts"],
                    "tp_price": tp, "sl_price": sl, "max_profit_price": entry_price,
                    "entry_bb_width": bb_width, "profit_mode": "normal",
                    "hma_gap_peak": 0.0
                }

            # ── CONFIRM 모드: 확인 대기 중인 브레이크아웃이 있으면 이번 캔들로 확정판정 ──
            if CONFIRM and pending is not None:
                still_fired = cw > pending["threshold"]
                same_dir = (
                    (pending["side"] == "long" and wi["candle_close"] > wi["candle_open"]) or
                    (pending["side"] == "short" and wi["candle_close"] < wi["candle_open"])
                )
                if still_fired and same_dir:
                    position = try_enter(pending["side"])
                pending = None
                continue  # 확인용으로 이번 캔들 소비, 새 스퀴즈 감지는 다음 캔들부터

            if squeeze_status == "normal":
                if cw < aw * SQUEEZE_ENTER_MULT:
                    squeeze_status = "squeeze"
                    squeeze_width = cw
            elif squeeze_status == "squeeze":
                if cw < squeeze_width:
                    squeeze_width = cw
                fired = cw > squeeze_width * BREAKOUT_MULT

                if fired:
                    squeeze_status = "normal"
                    signal = None
                    if wi["candle_close"] > wi["candle_open"]:
                        signal = "long"
                    elif wi["candle_close"] < wi["candle_open"]:
                        signal = "short"

                    if signal and not volume_ok(idx_prev):
                        signal = None  # 거래량 부족 - 브레이크아웃 무시

                    if signal and CONFIRM:
                        # 이번 캔들엔 진입 안 하고, 다음 캔들에서 재확인
                        pending = {"side": signal, "threshold": squeeze_width * BREAKOUT_MULT}
                    elif signal:
                        position = try_enter(signal)

    if position is not None:
        print(f"[진단] 백테스트 종료 시점에 미청산 포지션 존재: {position['side']} entry={position['entry']:.4f} mode={position['profit_mode']}")
    return trades, seed


def stats(trades, seed_final):
    n = len(trades)
    if n == 0:
        print("거래 없음")
        return
    wins = [t for t in trades if t["profit"] > 0]
    wr = len(wins) / n * 100
    gw = sum(t["profit"] for t in wins)
    gl = -sum(t["profit"] for t in trades if t["profit"] <= 0)
    pf = gw / gl if gl > 0 else float("inf")
    ret = (seed_final - SEED) / SEED * 100
    curve = [SEED]
    s = SEED
    for t in trades:
        s += t["profit"]
        curve.append(s)
    peak = curve[0]
    mdd = 0
    for v in curve:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak * 100)
    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    print(f"거래수 {n}  승률 {wr:.1f}%  PF {pf:.2f}  총수익률 {ret:+.2f}%  최종시드 ${seed_final:.2f}  MDD {mdd:.1f}%")
    print(f"종료사유: {reasons}")

    # 2026-08-07: "매도는 내가 차트보면서 할게, 진입만 잘하면돼" -> 봇 청산로직과 무관하게
    # 진입 후 도달했던 최고 평가수익률(peak_pct, 레버리지 반영)을 따로 집계.
    # "실현손익 평균"과 "최고평가수익 평균"의 차이가 클수록 = 사람이 직접 최고점 근처에서
    # 팔았을 때 이론상 더 벌 수 있는 여지(청산타이밍 알파)가 크다는 뜻.
    if all("peak_pct" in t for t in trades):
        avg_realized = sum(t["profit_pct"] for t in trades) / n
        avg_peak = sum(t["peak_pct"] for t in trades) / n
        thresholds = [1, 2, 3, 5, 10]
        over = {th: sum(1 for t in trades if t["peak_pct"] >= th) for th in thresholds}
        print(f"[진입품질] 거래당 평균 실현수익률(레버) {avg_realized:+.2f}%p  vs  평균 최고평가수익률(레버) {avg_peak:+.2f}%p"
              f"  (차이 {avg_peak - avg_realized:+.2f}%p = 청산타이밍 알파 여지)")
        over_str = ", ".join(f">={th}%: {over[th]}건({over[th]/n*100:.0f}%)" for th in thresholds)
        print(f"[진입품질] 최고평가수익률 도달 분포 - {over_str}")


if __name__ == "__main__":
    print(f"[{SYMBOL}] {DAYS}일치 {INTERVAL}분봉 데이터 수집 중...")
    candles = bt.fetch_klines(SYMBOL, INTERVAL, DAYS)
    print(f"캔들 {len(candles)}개 수집 완료")

    trades, final_seed = run(candles)
    print()
    if NO_SL:
        mode_label = "SL 없음 (청산 시뮬레이션만 유지)"
    elif FIXED_SL:
        mode_label = f"SL 고정 {SL_PERCENT*100:.1f}%"
    else:
        mode_label = f"SL = min(avg_width, {SL_PERCENT*100:.1f}%)"
    mode_label += f", BB밴드길이={WIDTH_LOOKBACK}"
    if CONFIRM:
        mode_label += ", 확인캔들ON"
    if BREAKOUT_MULT != 1.5:
        mode_label += f", 돌파배수={BREAKOUT_MULT}"
    if VOL_MULT is not None:
        mode_label += f", 거래량필터={VOL_MULT}x(최근{VOL_LOOKBACK}개평균)"
    if MA_TYPE != "hma":
        mode_label += f", MA종류={MA_TYPE.upper()}"
    if SINGLE_HMA:
        mode_label += ", 진입필터=HMA200단독"
    if HMA_FOLLOW:
        mode_label += ", HMA_FOLLOW(0단계=HMA200이탈시즉시청산, 1단계전환=HMA200/600정배열)"
    mode_label += f", {INTERVAL}분봉"
    print(f"=== 현재 라이브 로직 재현 백테스트 ({mode_label}) ===")
    stats(trades, final_seed)

    if "--table" in sys.argv:
        from datetime import datetime as _dt
        print()
        print("=== 거래별 상세 (기간별 수익률) ===")
        print(f"{'#':>3} {'방향':4} {'진입시각':16} {'청산시각':16} {'보유(h)':>7} {'진입가':>10} {'청산가':>10} {'사유':22} {'수익%':>8} {'손익$':>9} {'시드$':>10}")
        for i, t in enumerate(trades, 1):
            et = _dt.fromtimestamp(t["entry_ts"] / 1000)
            xt = _dt.fromtimestamp(t["exit_ts"] / 1000)
            hold_h = (t["exit_ts"] - t["entry_ts"]) / 1000 / 3600
            print(f"{i:>3} {t['side']:4} {et.strftime('%Y-%m-%d %H:%M'):16} {xt.strftime('%Y-%m-%d %H:%M'):16} "
                  f"{hold_h:7.1f} {t['entry']:10.4f} {t['exit']:10.4f} {t['reason']:22} "
                  f"{t['profit_pct']:+8.2f} {t['profit']:+9.2f} {t['seed_after']:10.2f}")
