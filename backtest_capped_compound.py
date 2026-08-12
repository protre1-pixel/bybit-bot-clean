"""2026-08-12 실험: "$4,000으로 시작해서 매 거래마다 잔고의 75%를 계속 복리로 태우다가,
계좌 잔고가 $40,000에 도달하는 순간부터는 더 이상 복리로 안 키우고 코인당 고정 $10,000의
75%씩만 고정으로 거래한다면?" (사용자 요청)

앞서 워크포워드 검증에서 sq=0.7/bo=1.6 조합이 무제한 복리 가정 하에서는 A구간 +710만%,
B구간 +7.8만% 같은 현실성 없는 수치가 나온 걸 확인했음. 이건 "계좌가 커져도 슬리피지/유동성
문제 없이 계속 잔고 비례로 베팅 사이즈를 키운다"는 비현실적 가정 때문. 이 스크립트는 일정
잔고($40,000) 도달 이후로는 베팅 사이즈를 고정시켜서(코인당 $10,000 기준 75%) 더 현실적인
성장 곡선을 시뮬레이션한다.

방법:
  1. 4개 코인(XRP/ETH/BTC/SOL) 15분봉 데이터를 현재 라이브 파라미터
     (sq=0.7, bo=1.6, profit_lock 0.5%/0.85, HMA200/600 regime filter)로 각각 백테스트해서
     거래 리스트(진입시각/pct 등)를 얻는다.
  2. 4개 코인의 거래를 entry_ts 기준으로 전부 시간순으로 합친다 (여러 코인이 동시에 포지션을
     잡을 수 있다는 기존 라이브 구조를 반영 - 공유 계좌 하나로 시뮬레이션).
  3. 계좌 잔고 총합 < $40,000인 동안: 매 거래 notional = 그 시점 총 잔고 × 75% × 레버리지(10)
     (지금까지 스크립트들과 동일한 복리 방식)
     계좌 잔고가 $40,000 이상이 된 "이후" 거래부터: notional = 고정 $10,000 × 75% × 레버리지(10)
     (더 이상 잔고 성장에 비례해서 커지지 않음. 손익 자체는 계속 총 잔고에 누적됨)
  4. 최종 잔고, $40,000 돌파 시점, 승률/PF/MDD를 출력.

사용법: python backtest_capped_compound.py [DAYS]
"""
import datetime
import sys

import backtest_current_live as bcl

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 730
COINS = ["XRPUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]
PLT, PLR = 0.5, 0.85

START_BALANCE = 4000.0
CAP_THRESHOLD = 40000.0
FIXED_BASE_PER_COIN = 10000.0

bcl.SQUEEZE_ENTER_MULT = 0.7
bcl.BREAKOUT_MULT = 1.6


if __name__ == "__main__":
    print(f"15분봉 {DAYS}일치 데이터 수집 및 백테스트 중 (코인 {len(COINS)}개, sq=0.7 bo=1.6)...", flush=True)
    all_trades = []
    for sym in COINS:
        candles = bcl.fetch_klines(sym, "15", DAYS)
        trades, _ = bcl.run_backtest(candles, profit_lock_trigger_pct=PLT, profit_lock_ratio=PLR,
                                      use_hma_regime_filter=True)
        for t in trades:
            t["symbol"] = sym
        all_trades.extend(trades)
        print(f"  {sym}: 캔들 {len(candles)}개, 거래 {len(trades)}건", flush=True)

    all_trades.sort(key=lambda t: t["entry_ts"])
    print(f"\n전체 거래 {len(all_trades)}건 시간순 정렬 완료. 시뮬레이션 시작...\n", flush=True)

    balance = START_BALANCE
    capped = False
    cap_hit_idx = None
    curve = [balance]
    recon = []

    for i, t in enumerate(all_trades):
        if not capped:
            notional = balance * bcl.ENTRY_PERCENT * bcl.LEVERAGE
        else:
            notional = FIXED_BASE_PER_COIN * bcl.ENTRY_PERCENT * bcl.LEVERAGE
        raw_pct = t["pct"] / 100
        pnl = notional * raw_pct - notional * bcl.FEE_RATE * 2
        balance += pnl
        curve.append(balance)
        recon.append({**t, "profit": pnl, "notional": notional, "capped": capped})

        if not capped and balance >= CAP_THRESHOLD:
            capped = True
            cap_hit_idx = i + 1
            dt = datetime.datetime.utcfromtimestamp(t["exit_ts"] / 1000)
            print(f"*** 거래 {cap_hit_idx}/{len(all_trades)}번째({dt.strftime('%Y-%m-%d')})에서 "
                  f"잔고 ${balance:,.2f}로 ${CAP_THRESHOLD:,.0f} 돌파! "
                  f"이후부터 코인당 고정 ${FIXED_BASE_PER_COIN:,.0f} 기준 75%로 사이즈 고정 ***", flush=True)

    n = len(recon)
    wins = [t for t in recon if t["profit"] > 0]
    losses = [t for t in recon if t["profit"] <= 0]
    win_rate = len(wins) / n * 100 if n else 0
    gross_win = sum(t["profit"] for t in wins)
    gross_loss = -sum(t["profit"] for t in losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    peak = curve[0]
    mdd = 0.0
    for v in curve:
        peak = max(peak, v)
        dd = (peak - v) / peak * 100 if peak > 0 else 0
        mdd = max(mdd, dd)

    print(f"\n{'='*70}")
    print(f"시작 잔고: ${START_BALANCE:,.2f}")
    print(f"최종 잔고: ${balance:,.2f}")
    print(f"총 수익률: {(balance - START_BALANCE) / START_BALANCE * 100:+,.2f}%")
    print(f"총 거래수: {n}건  승률: {win_rate:.1f}%  PF: {pf:.2f}  MDD: {mdd:.1f}%")
    if capped:
        print(f"$40,000 돌파 시점: {cap_hit_idx}/{n}번째 거래")
        print(f"고정사이즈 전환 이후 거래수: {n - cap_hit_idx}건")
        capped_only_pnl = sum(t['profit'] for t in recon if t['capped'])
        print(f"고정사이즈 전환 이후 순손익 합계: ${capped_only_pnl:,.2f}")
    else:
        print("$40,000 돌파 못함 (전체 기간 계속 복리 구간으로만 진행)")
    print(f"{'='*70}")
    print("\n=== CAPPED COMPOUND BACKTEST COMPLETE ===", flush=True)
