"""거래 로직"""
import logging
from datetime import datetime
from app.utils import load_state, save_state, load_trades, save_trades

logger = logging.getLogger(__name__)


BREAKOUT_MULTIPLIER = 1.6  # 스퀴즈 구간 평균 폭 대비 이만큼 넓어지면 발동
SQUEEZE_ENTER_MULT = 0.7  # 폭이 평균의 이 비율 이하로 눌리면 스퀴즈 진입
# 2026-08-12: 15분봉 sq/bo 재최적화 스윕(backtest_15m_regime_sweep.py) + 워크포워드
# 검증(backtest_15m_walkforward.py) 결과로 1시간봉(sq=0.5/bo=1.5) → 15분봉(sq=0.7/bo=1.6)
# + 진입필터를 HMA200/600 정배열(regime)로 교체. 신호·진입필터·청산로직(HMA200 Break,
# HMA 갭 추세추종) 전부 15분봉으로 통일해서 시간대 혼선 방지.
SQUEEZE_TIMEFRAME = 15  # 스퀴즈/브레이크아웃 신호 + 진입필터 + normal단계 HMA200 하드룰 공통 타임프레임

# 2026-08-16: backtest_archive/test_stallexit_fastbo_xrp_1y.py(XRP 15분봉 365일)로 검증한
# 최종 조합을 실거래에 반영. 기존(스퀴즈 상태머신 단독)에 아래 두 가지를 추가:
#   1) fast_breakout: 스퀴즈 선행조건(폭이 평균 이하로 눌림) 없이도, normal 상태에서
#      FAST_BREAKOUT_LOOKBACK캔들 전 폭 대비 지금 폭이 BREAKOUT_MULTIPLIER배 넘게 급확장하면
#      즉시 브레이크아웃으로 인정(스퀴즈 경로와 별개의 보조 경로). HMA200 Break 청산 비중을
#      19.9%→13.2%로 줄이면서 거래기회 자체도 늘림.
#   2) price_alignment_filter: apply_entry_filters에서 방향(HMA200/600 정배열 부호) 확정 후,
#      "가격도 이미 그 방향으로 완전히 정배열"(롱: price>HMA200>HMA600, 숏: 반대)된 상태일
#      때만 진입 허용 - 눌림목(진입 직후 HMA200 반대쪽에 있어 곧바로 0단계 하드룰에 걸리는
#      진입) 자체를 원천 차단.
# 두 가지 다 backtest_current_live.py의 use_fast_breakout / use_price_alignment_filter 옵션과
# 동일 로직. sq=0.7/bo=1.6 + 이 조합으로 XRP 231건 검증: PF 1.35, MDD 37.6%, 복리 +427.37%.
FAST_BREAKOUT_LOOKBACK = 2  # 스퀴즈 미충족 시 비교할 "N캔들 전" 폭 (BREAKOUT_MULTIPLIER 재사용)

# ── 수익 보호 단계 (Profit Staging) ────────────────────────────────
# 2026-08-05: 수익이 났다가 다시 손실로 반전되어 손절당하는 문제(SOXL, HOME 등 실거래
# 확인됨 - +2~3% 수익 구간까지 갔다가 그대로 반납하고 손실로 마감)를 막기 위해 도입.
# 2026-08-07(v2): 기존 1~3단계(퍼센트 기반 breakeven→partial_lock→trailing) 폐기.
# 사용자 판단 - "진입 타점만 정확하면, 청산은 차트(추세) 보고 판단해도 된다" → 퍼센트
# 임의값 대신 "추세가 살아있는 동안 계속 들고, 추세가 꺾이기 시작하면 정리"하는 방식으로
# 교체. 스퀴즈 진입 로직과 동일한 패턴(구간 동안의 "최댓값" 추적 후 비율 이탈 감지)을
# 15분봉 HMA(빠른)/HMA(느린) 갭에 적용.
# 2026-08-07(v3): 진입필터를 HMA200/600 정배열 → "HMA200 하나만"(가격 vs HMA200)으로
# 단순화. 대신 HMA200/600 정배열은 0단계→1단계 전환 트리거로 이동 - 사용자 판단
# "진입할때도 200일선 위아래 확인하고, 진입후에도 가격이 200일선보다 위면 유지하면서
# hma 600일선이 정배열로 놓이면 그때부턴 쭉 따라가는걸로":
#   0단계 normal       : 기존 BB평균폭(avg_width) 기반 동적 SL/TP 로 최소 방어.
#                        추가로 가격이 HMA200 유리한 쪽에서 벗어나면(휩소) 즉시 청산.
#   1단계 trend_follow : "최고수익 1%" 대신 HMA200/600 정배열이 트리거. 전환 즉시 SL을
#                        본전+수수료로 이동(최소 방어), 이후부턴 15분봉 HMA(HMA_GAP_FAST)/
#                        HMA(HMA_GAP_SLOW) 갭이 "진입 이후 가장 크게 벌어졌던 값" 대비
#                        HMA_GAP_CONTRACTION_RATIO 밑으로 줄어들면 SL을 현재가 근처로
#                        확 당겨서("슬슬 정리") 트레일링. 갭 부호 자체가 반전(추세 완전히
#                        꺾임)되면 즉시 전량 청산. TP 상한 없이 SL만으로 청산 판정.
# 2026-08-08(v4): 실거래 확인 - trend_follow 전환 직후(수익 거의 0%)에 본전 바닥이
# 즉시 걸리면서 정상적인 눌림(휩소)에도 바로 손절되는 문제 발생(SOL, +$2.36 63초만에 청산).
# 사용자 판단 - "출렁이는건 당연한건데 너무 빨리 판다, 적절한 조절 필요" → 본전 바닥은
# 최소 수익 쿠션이 생기기 전엔 걸지 않고, 수축 감지 민감도도 완화.
# STAGE1_TRIGGER_PCT는 더 이상 전환 트리거로 안 쓰지만(HMA 정배열로 대체) 상수는 유지.
STAGE1_TRIGGER_PCT = 1.0     # (미사용, 참고용) 본전 방어 + 추세추종 전환 시작 문턱 (원가 기준 %)
STAGE1_FEE_BUFFER_PCT = 0.15  # 본전 대비 여유(수수료 0.11% + 약간의 버퍼)
MIN_PROFIT_FOR_BREAKEVEN_PCT = 0.4  # trend_follow 전환 후 이 수익률(%) 넘기 전까진 본전 바닥 SL 자체를 걸지 않음

HMA_GAP_TIMEFRAME = 15        # 2026-08-12: 1시간봉→15분봉으로 재변경 - 신호/진입필터/청산 전부 15분봉 통일
HMA_GAP_FAST = 200            # 200×15분 = ~2.08일 lookback - 진입필터(HTF HMA200/600)와 동일 기간으로 통일
HMA_GAP_SLOW = 600            # 600×15분 = ~6.25일 lookback
HMA_GAP_CONTRACTION_RATIO = 0.4  # 갭이 진입후 최댓값의 이 비율 밑으로 줄면 "정리" 신호 (0.6→0.4, 더 깊게 눌려야 반응)
HMA_GAP_EXIT_BUFFER_PCT = 0.6    # 정리 신호 시 SL을 최고수익가에서 이만큼만 떨어진 곳으로 당김 (0.3→0.6, 숨쉴 틈 확보)
HMA_GAP_CACHE_SEC = 60         # HMA 갭 재계산 주기(초)

# 2026-08-10 v5: EPIC 실거래에서 최고+7.18% → 청산+0.04%로 거의 전액 반납된 사례 확인.
# trend_follow의 SL이 본전락/HMA갭수축 두 이벤트 사이엔 안 움직이는 구조적 문제 발견 →
# "최고수익 반납방지" 트레일링을 별도 레이어로 추가. peak_profit_pct가 PROFIT_LOCK_TRIGGER_PCT
# 이상이면, 그 이후로는 "최고수익 × PROFIT_LOCK_RATIO"는 반납해도 무조건 지키는 SL 하한선을
# HMA갭 수축 대기와 무관하게 매틱 갱신. backtest_current_live.py에서 4코인(XRP/ETH/BTC/SOL)
# x trigger[2/3/4%] x ratio[0.4~0.99] 스윕 검증 - ratio가 높을수록(타이트할수록) 예외 없이
# 전부 개선되는 단조 패턴 확인. 다만 실거래는 봉 중간 노이즈에 봉단위 백테스트보다 더 자주
# 걸릴 수 있어 0.99 대신 보수적으로 0.85 채택.
# 2026-08-12: trigger를 2.0 → 0.5로 낮춤. backtest_profit_lock_early.py 365일 1시간봉
# 스윕(XRP/ETH/BTC/SOL, ratio=0.85 고정)에서 trigger를 낮출수록 예외 없이 단조 개선
# (평균수익률 2.0%: +51.74% → 0.5%: +183.89%, 거래수/승률은 트리거값과 무관하게 동일 -
# 진입신호 왜곡 아닌 순수 exit 효율화로 확인). 더 낮은 값(<0.5%)은 미검증이라 0.5% 채택.
PROFIT_LOCK_TRIGGER_PCT = 0.5
PROFIT_LOCK_RATIO = 0.85

# 2026-08-16: giveback 진단 결과, 손실 대부분이 peak_pct < PROFIT_LOCK_TRIGGER_PCT(즉 profit_lock
# 트리거도 못 찍는) "초반 무동력" 거래 67건(비복리 $-8,136.61)에서 나온다는 게 확인됨. 반면 그
# 트리거를 넘긴 거래는 이미 profit_lock으로 반납이 거의 없어서(2%+ 그룹도 평균 0.87%p만 반납)
# trend_follow 트레일링 자체를 더 조이는 건 잘 달리는 추세만 건드릴 위험이 큼. 그래서 STALL_EXIT
# 조건을 PROFIT_LOCK_TRIGGER_PCT에 정확히 맞춰서, "이미 있는" stall_exit 옵션으로 그 67건 그룹만
# 선택적으로 SL을 조임 - 잘 달리는 거래는 이 조건에 걸리기 전에 이미 peak가 올라가 있어 전혀 영향
# 없음. backtest_archive/test_stallexit_fastbo_xrp_1y.py(XRP 15분봉 365일)에서 PF 1.13→1.35,
# MDD 61.5%→37.6%, 복리수익률 +188.91%→+427.37%로 개선 확인 후 적용.
STALL_EXIT_CANDLES = 8         # 진입 후 이 캔들수(15분봉×8=2시간) 지나도록 미달이면 SL 조임 대상
STALL_EXIT_MIN_PEAK_PCT = 0.5  # PROFIT_LOCK_TRIGGER_PCT와 동일 기준 (그 전까지 못 찍은 거래만 대상)
STALL_EXIT_SL_PCT = 0.4        # 조여지는 SL 폭 (진입가 대비 %, 기존 SL이 더 타이트하면 유지)

STAGE_LABEL = {
    "trend_follow": "Trend Follow",
}


HTF_TREND_CACHE_SEC = 300  # HMA200/600 진입필터 재조회 주기(초, API 부담 절감)


def apply_entry_filters(symbol, coin_key, signal, state, price):
    """2026-08-15: "전략#2"로 교체 - 기존(2026-08-12)엔 브레이크아웃 캔들의 몸통(양봉/음봉)으로
    방향을 먼저 정하고, HMA200/600 정배열과 불일치하면(예: 양봉인데 역배열) 진입을 취소했음.
    이 버전은 캔들 방향을 아예 보지 않고, 브레이크아웃이 뜬 순간의 HMA200/600 정배열(up)/
    역배열(down) 부호로 방향을 곧바로 결정해서 반환. 캔들-HMA 불일치로 인한 "취소, 재대기"가
    구조적으로 사라짐(HMA 계산 불가 시에만 취소로 남음). 백테스트(backtest_archive/
    backtest_current_live.py의 use_hma_direction_only, test_regime_direction_and_exit_xrp_1y.py,
    XRP 15분봉 1년)에서 기존 대비 PF 2.35→3.29, 승률 76.0%→83.0%, 거래당 평균수익
    +0.503%→+0.824%로 뚜렷한 개선 확인 후 사용자 판단으로 적용. signal 인자는 더 이상 방향
    판정에 쓰지 않음(호출부 시그니처 호환용으로만 유지). 청산(exit) 로직은 이 변경과 무관하게
    완전히 그대로 유지.
    2026-08-16 price_alignment_filter 추가: 방향(정배열 부호)만으로 진입하면 가격 자체는 아직
    HMA200 반대쪽(눌림목)에 있는 채로 진입하는 케이스가 생겨서, 진입 직후 0단계 HMA200 하드룰에
    바로 걸려 즉시청산되는 문제가 있었음. 그래서 방향 확정 후 "가격도 이미 그 방향으로 완전히
    정배열"(롱: price>HMA200>HMA600, 숏: price<HMA200<HMA600)된 상태일 때만 진입을 허용하도록
    추가 필터를 얹음(backtest_current_live.py의 use_hma_direction_only + use_price_alignment_filter
    조합과 동일 로직, test_stallexit_fastbo_xrp_1y.py로 최종 검증).
    캐시에는 HMA200/HMA600 raw 값을 저장 (가격과 무관하게 HMA 자체가 바뀌어야 갱신되므로 매
    폴링 재계산할 필요 없음 - price 정배열 판정은 캐시된 HMA값과 매 폴링의 실시간 price로 함)."""
    from app.services.price_service import calculate_hma

    # ── HMA200/HMA600 캐싱 (HTF_TREND_CACHE_SEC마다만 재조회) ──
    # 2026-08-12: normal단계 HMA200 하드룰이 쓰는 "htf_trend_cache"(단일 HMA200 값)와
    # 이름 충돌 방지를 위해 별도 캐시 키(entry_regime_cache) 사용.
    now_ts = datetime.now().timestamp()
    cache = state[coin_key].get("entry_regime_cache") or {}
    if "hma200" in cache and cache.get("ts") and (now_ts - cache["ts"]) < HTF_TREND_CACHE_SEC:
        hma200_now = cache.get("hma200")
        hma600_now = cache.get("hma600")
    else:
        hma200_now = calculate_hma(symbol, period=200, timeframe=SQUEEZE_TIMEFRAME)
        hma600_now = calculate_hma(symbol, period=600, timeframe=SQUEEZE_TIMEFRAME)
        state[coin_key]["entry_regime_cache"] = {"hma200": hma200_now, "hma600": hma600_now, "ts": now_ts}

    if hma200_now is None or hma600_now is None:
        logger.info(f"[FILTER] {coin_key}: HMA200/600 계산 불가 → 진입 취소")
        return None

    if hma200_now > hma600_now:
        htf_trend = "up"
    elif hma200_now < hma600_now:
        htf_trend = "down"
    else:
        htf_trend = None

    if htf_trend is None:
        logger.info(f"[FILTER] {coin_key}: HMA200/600 정배열 판정 불가(횡보) → 진입 취소")
        return None

    direction = "long" if htf_trend == "up" else "short"

    aligned = (
        (direction == "long" and price is not None and price > hma200_now > hma600_now) or
        (direction == "short" and price is not None and price < hma200_now < hma600_now)
    )
    if not aligned:
        logger.info(f"[FILTER] {coin_key}: regime={htf_trend}이지만 가격 정배열 불일치(눌림목, "
                    f"price={price}, hma200={hma200_now:.6f}, hma600={hma600_now:.6f}) → 진입 취소")
        return None

    return direction


def check_bollinger_band_signal(symbol, coin_key, state):
    """Squeeze Breakout 감지 (스퀴즈 구간 동안의 "최저점" 폭 대비 확 넓어지는 순간 + 캔들 방향
    + ADX/1h HTF 필터)

    변천사:
      v1(25시간 평균 기준): avg_width(최근 100개 15분봉≈25시간 평균) 대비 비교.
        평균이 너무 완만하게 움직여서 신호가 한참 늦게 나가는 문제.
      v2(스퀴즈 저점 하나만 기준, 2026-08-05 오전): 직전 squeeze 상태에서 "가장 좁았던
        순간의 폭 하나(squeeze_width)"만 계속 갱신해서 그 값의 1.5배와 비교.
        → 반응은 빨라졌지만, 저점이 그냥 우연히 찍힌 노이즈 하나여도 기준이 돼버려서
        실거래에서 사소한 등락에도 발동하는 문제가 확인됨 (SNDK 케이스: 45분 만에
        0.6% 가격 변동만으로 발동).
      v3(2026-08-05 오후~2026-08-07, 이후 롤백): "최저점 하나" 대신 스퀴즈 진입 이후
        계속 쌓이는 폭 샘플들의 "평균"을 실시간으로 갱신하면서, 그 평균 대비 지금
        폭이 1.5배를 넘을 때 발동.
      v4(2026-08-05 밤, 이후 롤백): v3까지는 breakout 캔들 자체에서 바로 진입했는데,
        실거래에서 "스파이크성 캔들 하나로 폭이 튀고 바로 되돌림 와서 손절"당하는
        케이스가 확인됨(BTC 사례: 폭이 스퀴즈 평균 대비 2.8배 튀어서 즉시 롱 진입 →
        47분 만에 SL). 그래서 다음 캔들에서 확장/방향이 유지되는지 확인하는
        "confirming" 상태를 추가했었으나, 백테스트 결과 실질적 개선 효과가
        불확실하고 진입이 한 캔들(15분)만큼 늦어지는 단점만 뚜렷해서 제거.
      v5(2026-08-06): confirming 단계 제거 - breakout 감지 즉시(지연 없이) 진입.
        BB period/width lookback을 10~20 → 30으로 늘려서(1시간 이내 타임프레임은
        30봉이 표준 기준) 폭 계산 자체의 노이즈를 줄임. 표준편차도 pandas/numpy
        양쪽 다 ddof=0(모집단)으로 통일해서 두 계산이 어긋나지 않게 함.
      v6(2026-08-07, 현재): 여러 코인(XRP/BTC/ETH/SOL/DOGE) 동시 백테스트로 v3(평균
        기준)보다 v2 방식(스퀴즈 진입 이후 "최저점"*1.5)이 전반적으로 더 낫다는 게
        확인돼서 v2 방식으로 되돌림. 대신 v2 단독 실거래에서 문제됐던 "우연한 노이즈
        저점 하나로 발동"을 ADX(14, 15분봉 추세강도+방향) 필터와 1시간봉 HTF
        HMA200/600 정배열 필터로 보완(apply_entry_filters). 필드명 squeeze_width는
        다시 "최솟값" 의미로 사용(squeeze_width_sum/count는 더 이상 안 씀).
    """
    from app.services.price_service import calculate_band_width_average

    try:
        # 1. 현재 BB 폭 계산 (+ 마지막 완성 캔들의 시가/종가/시각)
        # 2026-08-12: SQUEEZE_TIMEFRAME=15분봉으로 재변경 (사용자 판단, 15분봉 재최적화 결과 반영)
        width_info = calculate_band_width_average(symbol, lookback=30, timeframe=SQUEEZE_TIMEFRAME)
        if width_info is None:
            return None

        current_width = width_info["current_width"]
        avg_width = width_info["avg_width"]
        candle_open = width_info["candle_open"]
        candle_close = width_info["candle_close"]
        candle_time = width_info["candle_time"]

        # 2026-08-16: fast_breakout용 폭 히스토리 - 완성봉이 바뀔 때만 append(중복 방지).
        # 매 폴링(2초)마다 같은 완성봉을 반복 계산하므로 candle_time으로 새 캔들 여부 판단.
        width_history = state[coin_key].get("width_history") or []
        if not width_history or width_history[-1].get("time") != candle_time:
            width_history.append({"time": candle_time, "width": current_width})
            if len(width_history) > 10:
                width_history = width_history[-10:]
            state[coin_key]["width_history"] = width_history

        # 2. Squeeze/Breakout 상태 추적
        squeeze_status = state[coin_key].get("squeeze_status", "normal")

        # 3. 상태 머신
        if squeeze_status == "normal":
            # Squeeze 진입: 폭이 평균의 SQUEEZE_ENTER_MULT 이하로 눌렸을 때
            if current_width < avg_width * SQUEEZE_ENTER_MULT:
                state[coin_key]["squeeze_status"] = "squeeze"
                state[coin_key]["squeeze_width"] = current_width
                logger.info(f"[SQUEEZE] {coin_key}: Squeeze 감지 (폭: {current_width:.6f}, 평균: {avg_width:.6f})")

            elif len(width_history) > FAST_BREAKOUT_LOOKBACK:
                # 2026-08-16 fast_breakout: 스퀴즈 선행조건 없이도, FAST_BREAKOUT_LOOKBACK캔들
                # 전 폭 대비 지금 폭이 BREAKOUT_MULTIPLIER배 넘게 급확장했으면 즉시 브레이크아웃
                # 인정(스퀴즈 상태머신과 별개의 보조 경로 - squeeze_status는 건드리지 않음).
                past_width = width_history[-1 - FAST_BREAKOUT_LOOKBACK]["width"]
                if past_width > 0 and current_width > past_width * BREAKOUT_MULTIPLIER:
                    signal = apply_entry_filters(symbol, coin_key, None, state, candle_close)
                    if signal:
                        logger.info(
                            f"[FAST-BREAKOUT] {coin_key}: {FAST_BREAKOUT_LOOKBACK}캔들전 폭({past_width:.6f}) "
                            f"대비 급확장(폭 {current_width:.6f}×{BREAKOUT_MULTIPLIER}) → {signal.upper()} 즉시 진입"
                        )
                        return signal
                    else:
                        logger.info(f"[FAST-BREAKOUT] {coin_key}: 폭 급확장했지만 진입필터 불통과 → 재대기")

        elif squeeze_status == "squeeze":
            # 스퀴즈 진입 이후 계속 갱신되는 "최저점" 폭
            squeeze_min = state[coin_key].get("squeeze_width", current_width)
            if current_width < squeeze_min:
                squeeze_min = current_width
                state[coin_key]["squeeze_width"] = squeeze_min

            # Breakout 감지: 스퀴즈 구간 최저점 폭 대비 급확장됐을 때 즉시 발동 (확인봉 없음)
            if current_width > squeeze_min * BREAKOUT_MULTIPLIER:
                # 2026-08-15 "전략#2": 캔들 몸통(양봉/음봉)은 더 이상 방향 판정에 쓰지 않음.
                # 브레이크아웃이 뜬 순간의 HMA200/600 정배열(up)/역배열(down) 부호로 방향을
                # apply_entry_filters()에서 바로 결정 (백테스트 backtest_archive/
                # test_regime_direction_and_exit_xrp_1y.py에서 PF 2.35→3.29, 승률
                # 76.0%→83.0%로 개선 확인). 청산 로직은 완전히 그대로 유지.
                state[coin_key]["squeeze_status"] = "normal"

                signal = apply_entry_filters(symbol, coin_key, None, state, candle_close)

                if signal:
                    logger.info(
                        f"[BREAKOUT] {coin_key}: 밴드 확장(폭 {current_width:.6f} > "
                        f"스퀴즈최저점 {squeeze_min:.6f}×{BREAKOUT_MULTIPLIER}) → {signal.upper()} 즉시 진입"
                    )
                    return signal
                else:
                    # HMA200/600 정배열 판정 불가 → 재대기 (이미 normal로 리셋됨)
                    logger.info(f"[BREAKOUT] {coin_key}: 밴드 확장했지만 HMA200/600 정배열 판정 불가 → 진입 취소, 재대기")

        return None

    except Exception as e:
        logger.error(f"[ERROR] Squeeze Breakout 감지 에러: {coin_key} - {e}")
        return None


def check_entry_signal(symbol, coin_key, state):
    """진입 신호 확인 - Bollinger Band (1분봉)"""
    return check_bollinger_band_signal(symbol, coin_key, state)


def find_available_wallet(state):
    """사용 가능한 지갑 찾기"""
    wallets = state.get("wallets", {})
    for wallet_key in sorted(wallets.keys()):
        if not wallets[wallet_key].get("is_active"):
            return wallet_key
    return None


def rebalance_wallets_if_idle(state):
    """모든 지갑의 포지션이 종료된 시점에만 총시드를 지갑에 균등 재분배.

    지갑별로 손익이 누적되면 같은 수익률이라도 지갑마다 실제 수익 금액이
    달라진다 (수익난 지갑은 시드가 커지고, 손실난 지갑은 시드가 작아짐).
    하나라도 거래 중인 지갑이 있으면 재분배하지 않고, 모든 지갑이 유휴
    상태가 된 순간에만 한 번 총시드를 지갑 수만큼 균등하게 다시 나눈다.
    """
    wallets = state.get("wallets", {})
    if not wallets:
        return

    if any(wallet.get("is_active") for wallet in wallets.values()):
        return  # 아직 거래 중인 지갑이 있음 → 재분배 보류

    wallet_count = len(wallets)
    total_seed = state.get("total_seed", 0)
    new_seed = total_seed / wallet_count if wallet_count > 0 else 0

    for wallet in wallets.values():
        wallet["current_seed"] = new_seed

    logger.info(f"[REBALANCE] 모든 포지션 종료 - 지갑 재분배: 총시드 ${total_seed:.2f} ÷ {wallet_count}개 = 각 ${new_seed:.2f}")


def auto_trade(coin_key, symbol, state, username=None):
    """자동 거래 로직 (지갑 기반) - 전봉 기준"""
    try:
        current_price = state[coin_key]["current_price"]

        if current_price == 0:
            return

        # 거래 종료 후 30분 이내는 자동 거래 비활성화 (재진입 방지)
        try:
            if "last_close_time" in state[coin_key] and state[coin_key]["last_close_time"]:
                last_close_time = datetime.fromisoformat(state[coin_key]["last_close_time"])
                elapsed = (datetime.now() - last_close_time).total_seconds()
                if elapsed < 300:  # 300초 5분 , 1800초 = 30분
                    logger.debug(f"[DEBUG] {coin_key.upper()}: 거래 종료 후 {elapsed:.0f}초 대기 중 (30분 제한)...")
                    return
        except (ValueError, TypeError) as e:
            logger.warning(f"[WARN] last_close_time 파싱 실패 ({coin_key}): {e}")

        # 거래 진입 후 최소 1캔들(SQUEEZE_TIMEFRAME분)은 TP/SL 체크 안함
        # 2026-08-12: 60초 → 1캔들(15분)로 변경. 백테스트는 진입한 캔들에서는 절대
        # 청산 체크를 하지 않고(포지션 관리 로직이 진입 로직보다 먼저 실행되고, 매 반복이
        # 캔들 단위라 최초 청산 체크는 다음 캔들 = 최대 15분 후) - 특히 HMA200 Break(정배열
        # 진입해도 가격이 200선 근처/반대쪽에서 시작하는 눌림목 케이스)는 이 15분 동안 가격이
        # 유리하게 움직일 시간을 줘야 백테스트 승률(73.1%)이 재현됨. 라이브가 ~1분 폴링으로
        # 이 시간을 못 주면 같은 조건에서 실거래 손실률이 급증하는 것을 확인함 - 백테스트가
        # 실제로 검증한 시간창(1캔들)과 라이브를 맞추기 위한 수정.
        if state[coin_key]["position"] and state[coin_key]["entry_time"]:
            try:
                entry_time = datetime.fromisoformat(state[coin_key]["entry_time"])
                elapsed = (datetime.now() - entry_time).total_seconds()
                if elapsed < SQUEEZE_TIMEFRAME * 60:
                    return
            except (ValueError, TypeError) as e:
                logger.warning(f"[WARN] entry_time 파싱 실패 ({coin_key}): {e}")

        # TP/SL 체크 (normal → trend_follow(HMA 갭 추적))
        if state[coin_key]["position"]:
            from app.services.price_service import calculate_bollinger_bands, calculate_band_width_average, get_hma_gap
            from app.services.order_service import set_exchange_stop_loss

            entry_price = state[coin_key]["entry_price"]
            position_dir = state[coin_key]["position"]
            trade_mode = state.get("mode", "paper")
            order_symbol = f"{coin_key.upper()}USDT"

            # 수익률 계산 (현재가 기준)
            if position_dir == "long":
                profit_pct = (current_price - entry_price) / entry_price * 100
            else:  # short
                profit_pct = (entry_price - current_price) / entry_price * 100

            _valid_modes = {"normal", "trend_follow"}
            if state[coin_key].get("profit_mode") not in _valid_modes:
                state[coin_key]["profit_mode"] = "normal"

            profit_mode = state[coin_key]["profit_mode"]

            # 최고(유리한) 가격 갱신 - 모든 단계 공통
            max_profit_price = state[coin_key].get("max_profit_price") or entry_price
            is_new_high = (
                (position_dir == "long" and current_price > max_profit_price) or
                (position_dir == "short" and current_price < max_profit_price)
            )
            if is_new_high:
                state[coin_key]["max_profit_price"] = current_price
                max_profit_price = current_price

            if position_dir == "long":
                peak_profit_pct = (max_profit_price - entry_price) / entry_price * 100
            else:
                peak_profit_pct = (entry_price - max_profit_price) / entry_price * 100

            # ── 초반 무동력(stall) 방지: 단계(normal/trend_follow) 무관하게 항상 체크 ──
            # 2026-08-16: 진입 후 STALL_EXIT_CANDLES 캔들이 지나도록 peak_profit_pct가
            # STALL_EXIT_MIN_PEAK_PCT%도 못 찍었으면 SL을 entry∓STALL_EXIT_SL_PCT%로 강제로
            # 좁힘(기존 SL이 더 타이트하면 그대로 유지 - 완화는 안 함). STALL_EXIT_MIN_PEAK_PCT를
            # PROFIT_LOCK_TRIGGER_PCT와 동일하게 맞춰서, profit_lock 혜택을 못 받는 "정체된"
            # 거래만 정확히 겨냥(잘 달리는 거래는 이 조건에 걸리기 전에 이미 peak가 올라가 있어
            # 전혀 영향 없음). backtest_archive/test_stallexit_fastbo_xrp_1y.py로 검증.
            try:
                entry_time_dt = datetime.fromisoformat(state[coin_key]["entry_time"])
                candles_since_entry = int((datetime.now() - entry_time_dt).total_seconds() // (SQUEEZE_TIMEFRAME * 60))
            except (ValueError, TypeError):
                candles_since_entry = 0

            if candles_since_entry >= STALL_EXIT_CANDLES and peak_profit_pct < STALL_EXIT_MIN_PEAK_PCT:
                stall_sl = (entry_price * (1 - STALL_EXIT_SL_PCT / 100) if position_dir == "long"
                            else entry_price * (1 + STALL_EXIT_SL_PCT / 100))
                stall_updated = False
                if position_dir == "long" and stall_sl > state[coin_key]["sl_price"]:
                    state[coin_key]["sl_price"] = stall_sl
                    stall_updated = True
                elif position_dir == "short" and stall_sl < state[coin_key]["sl_price"]:
                    state[coin_key]["sl_price"] = stall_sl
                    stall_updated = True

                if stall_updated:
                    logger.info(f"[STALL-EXIT] {coin_key.upper()}: 진입후 {candles_since_entry}캔들 경과, "
                                f"최고수익 {peak_profit_pct:.2f}%(<{STALL_EXIT_MIN_PEAK_PCT}%) → SL 조임 (${stall_sl:.6f})")
                    sl_sync = set_exchange_stop_loss(order_symbol, stall_sl, mode=trade_mode)
                    if trade_mode == "live" and not sl_sync.get("success"):
                        logger.error(f"[ERROR] {coin_key.upper()} 거래소 SL 갱신 실패: {sl_sync.get('error')} - 소프트웨어 SL만으로 운용됨")

            # ── 0단계(normal): 가격이 HMA200 유리한 쪽에서 벗어나면 즉시 청산 ──
            # 2026-08-07 v3: 사용자 판단 - "진입후에도 가격이 200일선보다 위면 유지".
            # SL/TP 판정과 무관한 별개의 하드 룰(휩소 방지) - 진입필터(apply_entry_filters)와는
            # 별도 캐시(htf_trend_cache, 단일 HMA200 값)를 씀.
            # 2026-08-12: 1시간봉→15분봉으로 재변경 (사용자 판단, SQUEEZE_TIMEFRAME 통일).
            if profit_mode == "normal":
                from app.services.price_service import calculate_hma
                now_ts_h = datetime.now().timestamp()
                h_cache = state[coin_key].get("htf_trend_cache") or {}
                if "hma200" in h_cache and h_cache.get("ts") and (now_ts_h - h_cache["ts"]) < HTF_TREND_CACHE_SEC:
                    hma200_now = h_cache.get("hma200")
                else:
                    hma200_now = calculate_hma(symbol, period=200, timeframe=SQUEEZE_TIMEFRAME)
                    state[coin_key]["htf_trend_cache"] = {"hma200": hma200_now, "ts": now_ts_h}

                if hma200_now is not None:
                    broke_hma200 = (
                        (position_dir == "long" and current_price < hma200_now) or
                        (position_dir == "short" and current_price > hma200_now)
                    )
                    if broke_hma200:
                        logger.info(f"[HMA200-BREAK] {coin_key.upper()}: 가격이 HMA200 반대쪽으로 이탈 "
                                    f"(price={current_price:.6f}, hma200={hma200_now:.6f}) → 즉시 청산")
                        close_trade(coin_key, current_price, "HMA200 Break", state, username)
                        return

            # ── 단계 전환 판단 (한 번 올라간 단계는 절대 내려가지 않음) ──
            # 2026-08-07 v3: 트리거를 "최고수익 1%" 대신 "HMA200/600 정배열"로 교체
            # (사용자 판단 - "hma 600일선이 정배열로 놓이면 그때부턴 쭉 따라가는걸로").
            # 2026-08-12: 1시간봉→15분봉으로 재변경 (사용자 판단, SQUEEZE_TIMEFRAME 통일).
            stage_rank = {"normal": 0, "trend_follow": 1}
            current_rank = stage_rank.get(profit_mode, 0)
            target_mode = profit_mode

            if current_rank < 1:
                from app.services.price_service import get_htf_trend
                now_ts_a = datetime.now().timestamp()
                a_cache = state[coin_key].get("hma_align_cache") or {}
                if a_cache.get("ts") and (now_ts_a - a_cache["ts"]) < HTF_TREND_CACHE_SEC:
                    align_trend = a_cache.get("trend")
                else:
                    align_trend = get_htf_trend(symbol, fast_period=200, slow_period=600, timeframe=SQUEEZE_TIMEFRAME)
                    state[coin_key]["hma_align_cache"] = {"trend": align_trend, "ts": now_ts_a}

                stage_favorable = (
                    (position_dir == "long" and align_trend == "up") or
                    (position_dir == "short" and align_trend == "down")
                )
                if stage_favorable:
                    target_mode = "trend_follow"

            if target_mode != profit_mode:
                logger.info(f"[STAGE] {coin_key.upper()}: {profit_mode} → {target_mode} (최고수익 {peak_profit_pct:.2f}%)")
                state[coin_key]["profit_mode"] = target_mode
                profit_mode = target_mode
                # trend_follow 진입 직후 HMA 갭 최댓값 추적을 처음부터 새로 시작
                state[coin_key]["hma_gap_peak"] = 0

            # ── 1단계(trend_follow) SL 계산: 본전방어 + HMA 갭 추세추종 ──
            # 2026-08-07: 퍼센트 기반 partial_lock/trailing 폐기 - "추세(HMA 갭)가 살아있는
            # 동안은 계속 들고, 갭이 진입후 최댓값 대비 줄어들기 시작하면 정리" 방식으로 교체.
            # 스퀴즈 진입 로직(구간 최저점 추적 후 이탈 감지)과 동일한 패턴을 반대 방향
            # (최댓값 추적 후 수축 감지)으로 적용.
            staged_sl = None
            if profit_mode == "trend_follow":
                # 기본 바닥: 최소 수익 쿠션(MIN_PROFIT_FOR_BREAKEVEN_PCT)이 생기기 전엔 걸지 않음.
                # 전환 직후 수익이 거의 없는 상태에서 즉시 본전 SL이 걸리면 정상적인 눌림에도
                # 바로 손절되는 문제(SOL 사례) 방지 - 최소한의 여유가 생긴 뒤부터 본전 방어 시작.
                if peak_profit_pct >= MIN_PROFIT_FOR_BREAKEVEN_PCT:
                    staged_sl = (entry_price * (1 + STAGE1_FEE_BUFFER_PCT / 100) if position_dir == "long"
                                 else entry_price * (1 - STAGE1_FEE_BUFFER_PCT / 100))

                now_ts = datetime.now().timestamp()
                gap_cache = state[coin_key].get("hma_gap_cache") or {}
                if gap_cache.get("ts") and (now_ts - gap_cache["ts"]) < HMA_GAP_CACHE_SEC:
                    gap_info = gap_cache.get("gap_info")
                else:
                    gap_info = get_hma_gap(symbol, fast_period=HMA_GAP_FAST, slow_period=HMA_GAP_SLOW,
                                            timeframe=HMA_GAP_TIMEFRAME)
                    state[coin_key]["hma_gap_cache"] = {"gap_info": gap_info, "ts": now_ts}

                if gap_info is not None:
                    gap = gap_info["gap"]
                    favorable = (gap > 0) if position_dir == "long" else (gap < 0)

                    if not favorable:
                        # HMA 정배열/역배열이 완전히 반전(교차) - 추세 끝, 즉시 전량 청산
                        logger.info(f"[HMA-REVERSE] {coin_key.upper()}: 1h HMA{HMA_GAP_FAST}/{HMA_GAP_SLOW} 갭 반전"
                                    f"(gap={gap:.6f}) → 추세추종 종료, 즉시 청산")
                        close_trade(coin_key, current_price, "HMA Trend Reversal", state, username)
                        return

                    gap_abs = abs(gap)
                    gap_peak = max(state[coin_key].get("hma_gap_peak", 0), gap_abs)
                    state[coin_key]["hma_gap_peak"] = gap_peak

                    if gap_peak > 0 and gap_abs < gap_peak * HMA_GAP_CONTRACTION_RATIO:
                        # 갭 수축 감지(교차 전 조기 신호) - SL을 "최고수익가" 근처로 확 당겨서 "슬슬 정리"
                        # 2026-08-10: 기존엔 current_price 기준이라, 신호가 뜬 시점엔 이미 최고점에서
                        # 밀린 뒤라 그 눌린 가격 근처에 SL을 다시 그어서 최고점 수익을 거의 다 반납하고
                        # 본전 근처에서 잘리는 문제 확인(Trend Follow Stop 평균 -0.38%). max_profit_price
                        # 기준으로 바꿔서 신호가 뜨는 즉시 최고점 수익 대부분을 확정하도록 수정.
                        tight_sl = (max_profit_price * (1 - HMA_GAP_EXIT_BUFFER_PCT / 100) if position_dir == "long"
                                    else max_profit_price * (1 + HMA_GAP_EXIT_BUFFER_PCT / 100))
                        if staged_sl is None:
                            staged_sl = tight_sl
                        else:
                            staged_sl = max(staged_sl, tight_sl) if position_dir == "long" else min(staged_sl, tight_sl)
                        logger.debug(f"[HMA-CONTRACT] {coin_key.upper()}: 갭 {gap_abs:.6f} < 최댓값 {gap_peak:.6f}×"
                                     f"{HMA_GAP_CONTRACTION_RATIO} → SL 타이트닝 (${tight_sl:.6f})")

                # 2026-08-10 v5: 최고수익 반납 방지 트레일링 - HMA갭 수축 대기와 무관하게 매틱 체크.
                # peak_profit_pct가 PROFIT_LOCK_TRIGGER_PCT 이상이면 "최고수익 × PROFIT_LOCK_RATIO"는
                # 반납해도 무조건 지키는 SL 하한선을 추가로 후보에 올림(가장 유리한 후보가 최종 채택).
                if peak_profit_pct >= PROFIT_LOCK_TRIGGER_PCT:
                    locked_pct = peak_profit_pct * PROFIT_LOCK_RATIO
                    profit_lock_sl = (entry_price * (1 + locked_pct / 100) if position_dir == "long"
                                       else entry_price * (1 - locked_pct / 100))
                    if staged_sl is None:
                        staged_sl = profit_lock_sl
                    else:
                        staged_sl = max(staged_sl, profit_lock_sl) if position_dir == "long" else min(staged_sl, profit_lock_sl)
                    logger.debug(f"[PROFIT-LOCK] {coin_key.upper()}: 최고수익 {peak_profit_pct:.2f}% × "
                                 f"{PROFIT_LOCK_RATIO} 반납방지 SL 후보 (${profit_lock_sl:.6f})")

            if staged_sl is not None:
                sl_updated = False
                if position_dir == "long" and staged_sl > state[coin_key]["sl_price"]:
                    state[coin_key]["sl_price"] = staged_sl
                    sl_updated = True
                elif position_dir == "short" and staged_sl < state[coin_key]["sl_price"]:
                    state[coin_key]["sl_price"] = staged_sl
                    sl_updated = True

                if sl_updated:
                    logger.debug(f"[{STAGE_LABEL.get(profit_mode, profit_mode)}] {coin_key.upper()}: SL → ${staged_sl:.6f} (최고수익 {peak_profit_pct:.2f}%)")
                    sl_sync = set_exchange_stop_loss(order_symbol, staged_sl, mode=trade_mode)
                    if trade_mode == "live" and not sl_sync.get("success"):
                        logger.error(f"[ERROR] {coin_key.upper()} 거래소 SL 갱신 실패: {sl_sync.get('error')} - 소프트웨어 SL만으로 운용됨")

            # ── 0단계(normal): 평균 BB폭 기반 동적 SL/TP 갱신 (신고점 갱신 시에만) ──
            # 2026-08-07: bb["width"](그 순간 스냅샷)는 스퀴즈 직후라 좁게 나오는 경향이 있어서
            # avg_width(최근 구간 평균폭)로 교체 - 신고점 경신 때마다 계속 따라 올라가며 갱신됨.
            if profit_mode == "normal" and is_new_high:
                width_info = calculate_band_width_average(symbol, lookback=30, timeframe=SQUEEZE_TIMEFRAME)
                current_bb_width = width_info["avg_width"] if width_info else state[coin_key].get("entry_bb_width", 0)

                normal_sl_updated = False
                if position_dir == "long":
                    new_sl = max_profit_price - (current_bb_width * 0.8)
                    new_tp = max_profit_price + current_bb_width
                    if new_sl > state[coin_key]["sl_price"]:
                        state[coin_key]["sl_price"] = new_sl
                        normal_sl_updated = True
                    if new_tp > state[coin_key]["tp_price"]:
                        state[coin_key]["tp_price"] = new_tp
                else:
                    new_sl = max_profit_price + (current_bb_width * 0.8)
                    new_tp = max_profit_price - current_bb_width
                    if new_sl < state[coin_key]["sl_price"]:
                        state[coin_key]["sl_price"] = new_sl
                        normal_sl_updated = True
                    if new_tp < state[coin_key]["tp_price"]:
                        state[coin_key]["tp_price"] = new_tp

                if normal_sl_updated:
                    sl_sync = set_exchange_stop_loss(order_symbol, state[coin_key]["sl_price"], mode=trade_mode)
                    if trade_mode == "live" and not sl_sync.get("success"):
                        logger.error(f"[ERROR] {coin_key.upper()} 거래소 SL 갱신 실패: {sl_sync.get('error')} - 소프트웨어 SL만으로 운용됨")

            # ── 청산 판정 ──
            # normal 단계만 TP 상한을 둠. trend_follow 단계는
            # "추세가 커지면 계속 따라간다"는 목적이므로 TP 없이 SL(HMA 갭 추종)만으로 청산.
            if profit_mode == "normal":
                if position_dir == "long":
                    if current_price >= state[coin_key]["tp_price"]:
                        close_trade(coin_key, current_price, "Take Profit", state, username)
                        return
                    elif current_price <= state[coin_key]["sl_price"]:
                        close_trade(coin_key, state[coin_key]["sl_price"], "Stop Loss", state, username)
                        return
                else:
                    if current_price <= state[coin_key]["tp_price"]:
                        close_trade(coin_key, current_price, "Take Profit", state, username)
                        return
                    elif current_price >= state[coin_key]["sl_price"]:
                        close_trade(coin_key, state[coin_key]["sl_price"], "Stop Loss", state, username)
                        return
            else:
                reason = f"{STAGE_LABEL.get(profit_mode, profit_mode)} Stop"
                if position_dir == "long":
                    if current_price <= state[coin_key]["sl_price"]:
                        close_trade(coin_key, state[coin_key]["sl_price"], reason, state, username)
                        return
                else:
                    if current_price >= state[coin_key]["sl_price"]:
                        close_trade(coin_key, state[coin_key]["sl_price"], reason, state, username)
                        return

        # 진입 신호 체크
        if not state[coin_key]["position"]:
            is_recently_closed = False
            try:
                if "last_close_time" in state[coin_key] and state[coin_key]["last_close_time"]:
                    last_close_time = datetime.fromisoformat(state[coin_key]["last_close_time"])
                    elapsed = (datetime.now() - last_close_time).total_seconds()
                    if elapsed < 1800:  # 1800초 = 30분
                        is_recently_closed = True
            except (ValueError, TypeError):
                pass

            if not is_recently_closed:
                signal = check_entry_signal(symbol, coin_key, state)
                if signal:
                    # 사용 가능한 지갑 찾기
                    available_wallet = find_available_wallet(state)

                    if available_wallet:
                        wallets = state.get("wallets", {})
                        wallet = wallets[available_wallet]
                        current_seed = wallet.get("current_seed", 1000)
                        entry_percent = wallet.get("entry_percent", 75) / 100
                        leverage = wallet.get("leverage", 10)
                        tp_percent = wallet.get("tp", 3.0) / 100
                        sl_percent = wallet.get("sl", 3.5) / 100

                        # 포지션 계산
                        position_nominal = current_seed * entry_percent * leverage
                        position_size = position_nominal / current_price

                        # 실제 주문 (라이브/페이퍼)
                        from app.services.order_service import (
                            place_buy_order, place_sell_order, set_leverage,
                            get_fill_price, set_exchange_stop_loss
                        )
                        mode = state.get("mode", "paper")
                        order_symbol = f"{coin_key.upper()}USDT"

                        # 진입 전 거래소에 실제 레버리지 설정 (로컬 계산과 실제 마진이 어긋나는 것 방지)
                        leverage_result = set_leverage(order_symbol, leverage, mode=mode)
                        if not leverage_result.get("success"):
                            logger.error(f"[ERROR] {coin_key.upper()} 레버리지 설정 실패: {leverage_result.get('error')}")
                            return

                        if signal == "long":
                            order_result = place_buy_order(order_symbol, position_size, mode=mode)
                        else:  # short
                            order_result = place_sell_order(order_symbol, position_size, mode=mode)

                        if not order_result.get("success"):
                            logger.error(f"[ERROR] {coin_key.upper()} 주문 실패: {order_result.get('error')}")
                            return

                        # 실제 체결가 조회 (라이브 전용) - 봇이 관찰한 가격이 아니라 거래소가 실제로
                        # 체결시킨 평균가를 써야 슬리피지가 손익 계산에 정확히 반영됨
                        actual_entry_price = current_price
                        actual_position_size = order_result.get("qty", position_size)
                        fill = get_fill_price(order_symbol, order_result.get("order_id"), mode=mode)
                        if fill:
                            actual_entry_price = fill["avg_price"]
                            actual_position_size = fill["qty"] or actual_position_size
                            slippage_pct = (actual_entry_price - current_price) / current_price * 100
                            logger.info(f"[{coin_key.upper()}] 실제 체결가: ${actual_entry_price:.6f} (관찰가 ${current_price:.6f} 대비 슬리피지 {slippage_pct:+.3f}%)")
                        elif mode == "live":
                            logger.warning(f"[WARN] {coin_key.upper()} 실제 체결가 조회 실패 - 관찰가(${current_price:.6f})로 폴백")

                        # 거래 진입 상태 저장
                        state[coin_key]["position"] = signal
                        state[coin_key]["entry_price"] = actual_entry_price
                        state[coin_key]["entry_time"] = datetime.now().isoformat()
                        state[coin_key]["max_profit_price"] = actual_entry_price
                        state[coin_key]["wallet_id"] = available_wallet
                        state[coin_key]["position_size"] = actual_position_size
                        state[coin_key]["order_id"] = order_result.get("order_id")

                        # SL/TP 설정 (Bollinger Band 기반 - 진입 시점의 값 저장, 실제 체결가 기준)
                        # 2026-08-07: 진입 순간의 bb["width"](스퀴즈 브레이크아웃 직후라 아직
                        # 좁게 벌어진 상태 - 정의상 "이제 막 좁음을 벗어나는 중") 대신,
                        # calculate_band_width_average()의 avg_width(최근 구간 평균폭)를 초기
                        # TP/SL 폭 산정 기준으로 사용. 초기 SL이 너무 타이트해서 진입 직후
                        # 조기손절(0단계 SL비율이 코인별 46~70%로 압도적 1위 원인이었음)되는
                        # 문제를 avg_width로 완화. entry_bb_upper/lower(밴드 표시용)는
                        # calculate_bollinger_bands에서 그대로 가져옴 - TP/SL 폭 계산과는 무관.
                        # 2026-08-08: calculate_band_width_average를 여기서 직접 import하지 않고
                        # 위쪽 "이미 포지션 있음" 분기(248행)의 import에만 의존했더니, 새로 진입하는
                        # 이 분기는 그 코드를 안 타서 UnboundLocalError(referenced before assignment)가
                        # 매 진입마다 터짐 - TP/SL 계산이 중간에 끊겨 tp_price/sl_price가 None으로
                        # 남아버리는 실거래 사고로 이어졌음(XRP 무방비 포지션). 이 분기 자체에서
                        # 확실히 import하도록 수정.
                        from app.services.price_service import calculate_bollinger_bands, calculate_band_width_average
                        bb = calculate_bollinger_bands(coin_key, period=30, timeframe=SQUEEZE_TIMEFRAME)
                        width_info = calculate_band_width_average(coin_key, lookback=30, timeframe=SQUEEZE_TIMEFRAME)
                        avg_width = width_info["avg_width"] if width_info else None

                        # 레버리지 청산 위험을 고려한 SL 거리 상한선.
                        # (2026-08-05 밤: UAI 실거래에서 BB폭이 넓어 SL이 진입가 대비 10.83%까지
                        #  벌어진 사례 확인 - 10배 레버리지의 이론상 청산선(~9~10%)을 넘어버려서
                        #  봇의 SL이 발동하기 전에 거래소 강제청산이 먼저 올 수 있는 위험이었음.
                        #  ① 지갑에 설정된 sl_percent, ② 레버리지 기준 이론상 청산선의 80% 지점
                        #  중 더 타이트한 쪽을 SL 거리의 상한으로 강제 적용. 2026-08-07: sl_percent
                        #  기본값을 1.5%→3.0%로 올렸지만 이 min() 캡 로직 자체는 변경 없음 -
                        #  avg_width가 아무리 커도 실제 주문 SL은 여전히 이 상한을 넘지 않음)
                        leverage_safety_pct = (1 / leverage) * 0.8 if leverage > 0 else sl_percent
                        max_sl_distance_pct = min(sl_percent, leverage_safety_pct)
                        max_sl_distance = actual_entry_price * max_sl_distance_pct

                        if avg_width:
                            # 진입 시점의 BB 값을 저장 (나중에 변하지 않도록) - upper/lower는 표시용
                            state[coin_key]["entry_bb_upper"] = bb["upper"] if bb else None
                            state[coin_key]["entry_bb_lower"] = bb["lower"] if bb else None
                            state[coin_key]["entry_bb_width"] = avg_width

                            # avg_width를 기반으로 TP/SL 설정 (실제 체결가를 기준으로)
                            # 최소 수익률 0.2% (거래 수수료 0.11% + 마진 0.09%)를 보장
                            bb_width = max(avg_width, actual_entry_price * 0.002)

                            # SL 거리는 avg_width와 안전 상한선 중 더 작은 쪽 사용
                            # (TP는 청산 위험이 없으므로 avg_width 그대로 유지 - 비대칭 허용)
                            sl_distance = min(bb_width, max_sl_distance)
                            if bb_width > max_sl_distance:
                                logger.warning(
                                    f"[SL-CAP] {coin_key.upper()}: 평균폭 기반 SL({bb_width / actual_entry_price * 100:.2f}%)이 "
                                    f"안전 상한({max_sl_distance_pct * 100:.2f}%, 레버리지 {leverage}배)을 초과해 상한으로 축소"
                                )

                            if signal == "long":
                                # LONG: TP = 체결가 + BB width, SL = 체결가 - SL거리(상한 적용)
                                state[coin_key]["tp_price"] = actual_entry_price + bb_width
                                state[coin_key]["sl_price"] = actual_entry_price - sl_distance
                            else:  # short
                                # SHORT: TP = 체결가 - BB width, SL = 체결가 + SL거리(상한 적용)
                                state[coin_key]["tp_price"] = actual_entry_price - bb_width
                                state[coin_key]["sl_price"] = actual_entry_price + sl_distance
                        else:
                            # BB 계산 실패시 고정 % 사용 (이것도 레버리지 안전 상한 적용)
                            state[coin_key]["entry_bb_upper"] = None
                            state[coin_key]["entry_bb_lower"] = None
                            state[coin_key]["entry_bb_width"] = None

                            if signal == "long":
                                state[coin_key]["tp_price"] = actual_entry_price * (1 + tp_percent)
                                state[coin_key]["sl_price"] = actual_entry_price - max_sl_distance
                            else:
                                state[coin_key]["tp_price"] = actual_entry_price * (1 - tp_percent)
                                state[coin_key]["sl_price"] = actual_entry_price + max_sl_distance

                        # 거래소에 실제 SL 설정 (봇 다운 시에도 거래소가 지켜주는 최후 안전망)
                        sl_sync_result = set_exchange_stop_loss(order_symbol, state[coin_key]["sl_price"], mode=mode)
                        if mode == "live" and not sl_sync_result.get("success"):
                            logger.error(f"[ERROR] {coin_key.upper()} 거래소 SL 설정 실패: {sl_sync_result.get('error')} - 소프트웨어 SL만으로 운용됨")

                        # 지갑 활성화
                        wallet["is_active"] = True
                        wallet["assigned_coin"] = coin_key

                        logger.info(f"[{coin_key.upper()}] {signal.upper()} 진입 ({available_wallet}, {mode}): {actual_entry_price} | TP: ${state[coin_key]['tp_price']:.6f} | SL: ${state[coin_key]['sl_price']:.6f}")
                    else:
                        logger.debug(f"[{coin_key.upper()}] 신호 발생하나 사용 가능한 지갑 없음 (모두 거래 중)")
    except Exception as e:
        logger.error(f"[ERROR] auto_trade ({coin_key}): {e}")


def close_trade(coin_key, exit_price, reason, state, username=None):
    """거래 종료 및 기록"""
    try:
        # 포지션이 없으면 거래 불가 (이미 닫혀있음)
        if not state[coin_key].get("position"):
            logger.warning(f"[{coin_key.upper()}] 이미 닫혀있는 포지션 - close_trade 무시")
            return 0

        entry_price = state[coin_key]["entry_price"]
        position_size = state[coin_key]["position_size"]
        position_dir = state[coin_key]["position"]

        # 포지션 종료 주문 (라이브/페이퍼) - long은 매도로, short은 매수(환매)로 청산
        from app.services.order_service import place_buy_order, place_sell_order, get_fill_price
        mode = state.get("mode", "paper")
        close_side = "long" if position_dir == "long" else "short"
        order_symbol = f"{coin_key.upper()}USDT"

        # 실제 체결가는 아래에서 확정. 기본값은 목표가(SL/TP 트리거가) - 페이퍼 모드/조회 실패 시 폴백
        actual_exit_price = exit_price

        if mode == "live" and position_size > 0:
            # 라이브 모드: 실제 청산 주문
            if close_side == "long":
                order_result = place_sell_order(order_symbol, position_size, mode=mode, reduce_only=True)
            else:
                order_result = place_buy_order(order_symbol, position_size, mode=mode, reduce_only=True)

            if not order_result.get("success"):
                logger.error(f"[ERROR] {coin_key.upper()} 청산 주문 실패: {order_result.get('error')}")
            else:
                # 실제 체결가 조회 - 목표가(SL/TP)가 아니라 거래소가 실제로 청산시킨 가격을 손익 계산에 사용
                fill = get_fill_price(order_symbol, order_result.get("order_id"), mode=mode)
                if fill:
                    actual_exit_price = fill["avg_price"]
                    slippage_pct = (actual_exit_price - exit_price) / exit_price * 100
                    logger.info(f"[{coin_key.upper()}] 실제 청산 체결가: ${actual_exit_price:.6f} (목표가 ${exit_price:.6f} 대비 슬리피지 {slippage_pct:+.3f}%)")
                else:
                    logger.warning(f"[WARN] {coin_key.upper()} 실제 청산 체결가 조회 실패 - 목표가(${exit_price:.6f})로 폴백")
        else:
            # 페이퍼 모드: 시뮬레이션
            action = "매도" if close_side == "long" else "매수(환매)"
            logger.info(f"[PAPER] {action}: {coin_key.upper()} × {position_size}")

        exit_price = actual_exit_price  # 이후 손익 계산/기록은 전부 실제 체결가 기준

        # Bybit 시장가 수수료: 0.055% (진입 + 청산)
        fee_rate = 0.00055
        entry_cost = entry_price * position_size
        exit_value = exit_price * position_size

        # 수수료 계산
        entry_fee = entry_cost * fee_rate
        exit_fee = exit_value * fee_rate
        total_fee = entry_fee + exit_fee

        # 순수익 = 차익 - 총 수수료
        if position_dir == "long":
            gross_profit = (exit_price - entry_price) * position_size
        else:  # short
            gross_profit = (entry_price - exit_price) * position_size
        profit = gross_profit - total_fee

        # 수익률: 진입가 기준 포지션 변화율 (수수료 반영)
        profit_pct = ((profit / entry_cost) * 100) if entry_cost > 0 else 0

        # 거래 기록 저장
        trades = load_trades(username)
        entry_time = state[coin_key]["entry_time"]

        # 중복 확인: 같은 entry_time의 거래가 이미 있으면 무시
        existing_trade = next((t for t in trades if t.get("entry_time") == entry_time and t.get("coin").lower() == coin_key.lower()), None)
        if existing_trade:
            logger.warning(f"[{coin_key.upper()}] 이미 저장된 거래 (entry_time={entry_time}) - 중복 저장 무시")
            return profit  # 수익 반환하지만 기록 저장 안 함

        # 실제 손실/수익 기반으로 재계산하여 일관성 확보
        actual_position_size = state[coin_key]["position_size"]
        actual_entry_price = state[coin_key]["entry_price"]
        actual_profit = profit
        actual_profit_pct = profit_pct

        trade = {
            "coin": coin_key.upper(),
            "type": state[coin_key]["position"].upper(),
            "entry_price": round(actual_entry_price, 6),
            "exit_price": round(exit_price, 6),
            "entry_time": entry_time,
            "exit_time": datetime.now().isoformat(),
            "profit": round(profit, 2),
            "profit_pct": round(profit_pct, 2),
            "position_size": round(actual_position_size, 8),
            "reason": reason
        }
        trades.append(trade)
        save_trades(trades, username)

        # 지갑 손익 누적 (지갑 기반 복리)
        wallet_id = state[coin_key].get("wallet_id")
        if wallet_id and "wallets" in state and wallet_id in state["wallets"]:
            wallet = state["wallets"][wallet_id]
            wallet["current_seed"] = wallet.get("current_seed", 1000) + profit
            wallet["is_active"] = False
            wallet["assigned_coin"] = None
            logger.info(f"[{wallet_id}] 손익 누적: ${profit:.2f} → 새로운 시드: ${wallet['current_seed']:.2f}")

        # 마진 업데이트 (하위 호환성 유지)
        state[coin_key]["margin"] += profit

        # 총시드 업데이트 (모든 지갑 손익 합산)
        state["total_seed"] += profit

        # 모든 지갑이 유휴 상태(포지션 없음)가 됐다면 시드 재분배
        rebalance_wallets_if_idle(state)

        # 포지션 반드시 리셋 (available_coins 상관없이!)
        state[coin_key]["position"] = None
        state[coin_key]["entry_price"] = None
        state[coin_key]["entry_time"] = None
        state[coin_key]["profit"] = 0
        state[coin_key]["profit_pct"] = 0
        state[coin_key]["position_size"] = 0
        state[coin_key]["max_profit_price"] = None
        state[coin_key]["tp_price"] = None
        state[coin_key]["sl_price"] = None
        state[coin_key]["wallet_id"] = None
        state[coin_key]["profit_mode"] = "normal"  # ← 거래 종료 시 리셋!
        state[coin_key]["last_close_time"] = datetime.now().isoformat()

        logger.info(f"[{coin_key.upper()}] 거래 종료: {reason}, 수익: ${profit:.2f}")

        # 상태 즉시 저장 (중요!)
        save_state(state, username)

        return profit  # 수익 반환
    except Exception as e:
        logger.error(f"[ERROR] close_trade ({coin_key}): {e}")
        return 0
