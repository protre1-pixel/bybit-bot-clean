"""
2026-08-19(35차): 사용자가 스퀴즈-브레이크아웃 전략의 근본 한계를 지적함 - "스퀴즈 없이
완만하게(서서히 밴드가 벌어지며) 계속 좋은 추세로 오르는 구간"(차트 스크린샷의 흰색 박스
2개 구간)은 지금 로직(SQUEEZE_ENTER_MULT=0.7로 스퀴즈 인정 + BREAKOUT_MULT=1.6배 급확장)
으로는 원천적으로 못 잡는다는 걸 설명함. 사용자가 "sq(0.85)·bo(1.3)로 테스트 해봐"라고
요청 - 두 임계값을 느슨하게(스퀴즈 인정 쉽게 0.7→0.85, 브레이크아웃 확장폭 완화 1.6→1.3)
바꿔서 완만한 추세도 잡히는지, 그 대신 노이즈성 잔파도에 더 자주 낚여서 전체 성과가
나빠지는지(트레이드오프) 확인.

방법: test_min_hold_3h_lev5_16sl_4coin_1y.py(34차, 현재 라이브와 100% 동일한 하이브리드
패치 구조 - 3시간 보유창 + 16% 파국적SL + 레버리지5)를 그대로 재사용하고, 딱 두 상수만
교체: `bcl.SQUEEZE_ENTER_MULT = 0.85`(기존 0.7), `bcl.BREAKOUT_MULT = 1.3`(기존 1.6).
나머지(LIVE_KWARGS, MIN_HOLD_CANDLES=12, HOLD_CAT_SL_PCT=16.0, TEST_LEVERAGE=5)는 전부 동일.

비교 대상(CURRENT_LIVE, 34차 결과 - backtest_archive/2026-08-18_leverage5_3h_hold_16sl_deploy.md
에 기록된 실제 배포 근거 수치, 재실행 안 하고 그대로 재사용):
BTC n=227 승률67.8% PF2.67 MDD8.9% 비복리+141.6% 캣SL0건
ETH n=239 승률64.4% PF2.99 MDD9.5% 비복리+218.6% 캣SL0건
XRP n=220 승률75.0% PF4.92 MDD12.8% 비복리+188.2% 캣SL0건
SOL n=251 승률69.3% PF3.88 MDD20.8% 비복리+228.5% 캣SL0건

스코프: BTCUSDT/ETHUSDT/XRPUSDT/SOLUSDT, 15분봉, 365일.
"""
import sys
import os
import inspect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_current_live as bcl

_src = inspect.getsource(bcl.run_backtest)

_SIG_OLD = "def run_backtest(candles, hma200_buffer_pct=0.0,"
_SIG_NEW = ("def run_backtest_min_hold_hybrid(candles, min_hold_candles=None, "
            "hold_cat_sl_pct=8.5, hma200_buffer_pct=0.0,")
assert _src.count(_SIG_OLD) == 1, "run_backtest 시그니처가 바뀐 듯 - 확인 필요"
_src = _src.replace(_SIG_OLD, _SIG_NEW, 1)

# --- 패치 1: 홀드 플래그 + 캐터스트로픽 SL 체크를 exit_price/reason 초기화 직후 삽입 ---
_GATE_ANCHOR = "            exit_price = None\n            reason = None"
assert _src.count(_GATE_ANCHOR) == 1, "gate anchor가 바뀐 듯 - 확인 필요"
_GATE_PATCHED = (
    _GATE_ANCHOR + "\n\n"
    "            in_hold_window = (min_hold_candles is not None\n"
    "                               and (t - position[\"entry_t\"]) < min_hold_candles)\n"
    "            if in_hold_window:\n"
    "                if side == \"long\":\n"
    "                    cat_sl_price = entry * (1 - hold_cat_sl_pct / 100)\n"
    "                    if low <= cat_sl_price:\n"
    "                        exit_price, reason = cat_sl_price, \"Catastrophic SL (hold)\"\n"
    "                else:\n"
    "                    cat_sl_price = entry * (1 + hold_cat_sl_pct / 100)\n"
    "                    if high >= cat_sl_price:\n"
    "                        exit_price, reason = cat_sl_price, \"Catastrophic SL (hold)\"\n"
)
assert _src.count(_GATE_ANCHOR) == 1  # sanity (아직 원본에 1회만 존재해야 함)
_src = _src.replace(_GATE_ANCHOR, _GATE_PATCHED, 1)

# --- 패치 2: stall_exit ~ 최종 SL/TP 판정 블록 전체를 `if not in_hold_window:` 로 래핑 ---
_BLOCK_START = "            # 2026-08-16: \"초반 무동력\" 조기청산 - 진입 후 stall_exit_candles개 캔들이"
_BLOCK_END = ("            if exit_price is not None:\n"
              "                raw_pct = (exit_price - entry) / entry if side == \"long\" else (entry - exit_price) / entry")
assert _src.count(_BLOCK_START) == 1, "block start anchor가 바뀐 듯 - 확인 필요"
assert _src.count(_BLOCK_END) == 1, "block end anchor가 바뀐 듯 - 확인 필요"

_start_idx = _src.index(_BLOCK_START)
_end_idx = _src.index(_BLOCK_END)
assert _start_idx < _end_idx

_middle = _src[_start_idx:_end_idx]
_middle_reindented = "\n".join(
    ("    " + line) if line.strip() != "" else line
    for line in _middle.split("\n")
)
_wrapped = "            if not in_hold_window:\n" + _middle_reindented

_src = _src[:_start_idx] + _wrapped + _src[_end_idx:]

_ns = bcl.__dict__
exec(compile(_src, "<min_hold_hybrid_variant>", "exec"), _ns)
run_backtest_min_hold_hybrid = _ns["run_backtest_min_hold_hybrid"]

SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT"]
INTERVAL = "15"
DAYS = 365
MIN_HOLD_CANDLES = 12  # 15m x 12 = 3시간
HOLD_CAT_SL_PCT = 16.0
TEST_LEVERAGE = 5

# 34차(현재 라이브) 대비 오늘 바꾸는 값
NEW_SQUEEZE_ENTER_MULT = 0.85  # 기존 0.7 -> 완화(더 쉽게 스퀴즈로 인정)
NEW_BREAKOUT_MULT = 1.3        # 기존 1.6 -> 완화(더 작은 확장에도 브레이크아웃 인정)

LIVE_KWARGS = dict(
    profit_lock_trigger_pct=0.5,
    profit_lock_ratio=1.0,
    use_price_alignment_filter=True,
    stall_exit_candles=8, stall_exit_min_peak_pct=0.5,
    stall_exit_sl_pct=0.4,
    use_hma_direction_only=True,
    use_fast_breakout=True, fast_breakout_lookback=2, fast_breakout_mult=None,
    use_regime_exit=True,
)

# 34차(현재 라이브, 2026-08-18 배포 근거) 결과 재사용 - 재실행 안 함
CURRENT_LIVE = {
    "BTCUSDT": dict(n=227, win_rate=67.8, pf=2.67, mdd=8.9, sum_pct=141.6, cat_sl_count=0),
    "ETHUSDT": dict(n=239, win_rate=64.4, pf=2.99, mdd=9.5, sum_pct=218.6, cat_sl_count=0),
    "XRPUSDT": dict(n=220, win_rate=75.0, pf=4.92, mdd=12.8, sum_pct=188.2, cat_sl_count=0),
    "SOLUSDT": dict(n=251, win_rate=69.3, pf=3.88, mdd=20.8, sum_pct=228.5, cat_sl_count=0),
}


def summarize(trades, seed_end):
    wins = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] <= 0]
    win_rate = len(wins) / len(trades) * 100
    gross_win = sum(t["profit"] for t in wins)
    gross_loss = -sum(t["profit"] for t in losses)
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")

    equity = [bcl.SEED]
    run = bcl.SEED
    for t in trades:
        run += t["profit"]
        equity.append(run)
    peak = equity[0]
    mdd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = (peak - e) / peak * 100 if peak > 0 else 0
        if dd > mdd:
            mdd = dd

    avg_hold = sum(t["hold_h"] for t in trades) / len(trades)
    total_return = (seed_end - bcl.SEED) / bcl.SEED * 100
    sum_pct = sum(t["pct"] for t in trades)

    cat_sl_count = sum(1 for t in trades if t["reason"] == "Catastrophic SL (hold)")

    return dict(n=len(trades), win_rate=win_rate, pf=pf, mdd=mdd, avg_hold=avg_hold,
                sum_pct=sum_pct, total_return=total_return, cat_sl_count=cat_sl_count)


results = {}

for symbol in SYMBOLS:
    print(f"\n{'#'*60}\n# {symbol}\n{'#'*60}")
    bcl.SQUEEZE_ENTER_MULT = NEW_SQUEEZE_ENTER_MULT
    bcl.BREAKOUT_MULT = NEW_BREAKOUT_MULT
    bcl.LEVERAGE = TEST_LEVERAGE
    candles = bcl.fetch_klines(symbol, INTERVAL, DAYS)

    trades, seed_end = run_backtest_min_hold_hybrid(
        candles, min_hold_candles=MIN_HOLD_CANDLES, hold_cat_sl_pct=HOLD_CAT_SL_PCT, **LIVE_KWARGS)
    s = summarize(trades, seed_end)
    results[symbol] = s

    print(f"[{symbol}/SQ0.85_BO1.3] 거래수 {s['n']}건  승률 {s['win_rate']:.1f}%  "
          f"PF {s['pf']:.2f}  MDD {s['mdd']:.1f}%  평균보유 {s['avg_hold']:.1f}h  "
          f"비복리합산 {s['sum_pct']:+.1f}%  캐터스트로픽SL발동 {s['cat_sl_count']}건", flush=True)

print(f"\n{'='*100}\n[종합: 현재 라이브(SQ0.7/BO1.6) vs SQ0.85/BO1.3(완화)]\n{'='*100}")
print("| 심볼 | 버전 | 거래수 | 승률 | PF | MDD | 비복리합산% | 캣SL발동 |")
print("|---|---|---|---|---|---|---|---|")
for symbol in SYMBOLS:
    c = CURRENT_LIVE[symbol]
    n = results[symbol]
    pfn = f"{n['pf']:.2f}" if n['pf'] != float("inf") else "inf"
    print(f"| {symbol} | 현재라이브(SQ0.7/BO1.6) | {c['n']} | {c['win_rate']:.1f}% | {c['pf']:.2f} | "
          f"{c['mdd']:.1f}% | {c['sum_pct']:+.1f}% | {c['cat_sl_count']}건 |")
    print(f"| {symbol} | SQ0.85/BO1.3(신규) | {n['n']} | {n['win_rate']:.1f}% | {pfn} | "
          f"{n['mdd']:.1f}% | {n['sum_pct']:+.1f}% | {n['cat_sl_count']}건 |")

print("\n=== SQ0.85 / BO1.3 (LEVERAGE 5x, 3H HOLD, 16% CAT SL) 4-COIN 1Y TEST COMPLETE ===", flush=True)
