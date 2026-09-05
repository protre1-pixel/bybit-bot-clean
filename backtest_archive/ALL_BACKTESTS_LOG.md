# 백테스트 전체 로그 (2026-08-07 ~ 2026-09-05)

이 문서는 `backtest_archive/` 폴더에 쌓인 **테스트 스크립트 167개 전체**(`test_*.py` 기준
111개 + 지원 스크립트)를 날짜순으로 정리한 종합 색인이다. 실제 배포로 이어진 주요
변경은 별도의 `YYYY-MM-DD_..._deploy.md` 문서에 배경/검증/변경내용/배포절차까지 상세히
기록되어 있으므로, 이 문서에서는 **한 줄 요약 + 해당 deploy.md 링크**로만 표시하고,
배포로 이어지지 않은 조사/기각된 실험은 이 문서가 유일한 기록이므로 조금 더 자세히 적었다.

전체적인 전략 구조(진입/청산/자금운용) 자체는 `STRATEGY_OVERVIEW.md` 참고.

---

## 2026-08-07 — 초기 전략 탐색 (BB스퀴즈 vs HMA cross vs SuperTrend류)

아직 "라이브 로직 그대로 재현"하는 `backtest_current_live.py` 체계가 없던 초기 단계.
개별 아이디어를 하나씩 스크립트로 만들어 검증하던 시기.

- `test_squeeze_min115.py` — 스퀴즈 판정 방식(평균 대비 vs 롤링최솟값) + ADX/DI 필터 조합 스윕.
- `test_live_staging.py` — 4단계 티어드 SL(`live_staging`) vs 기존 2단계 단순 청산 비교.
- `test_stage_sweep.py` — Stage1/2/3 트리거·락·트레일 파라미터 5개 조합(A~E) 스윕.
- `test_hma_cross.py` — BB스퀴즈 없이 순수 HMA200/600 골든/데드크로스만으로 진입, 일봉.
- `test_hma_cross_15m.py` — 위와 동일 로직을 15분봉/6개월로 재검증.
- `test_hma_simple.py` — 레버리지/수수료/포지션사이징 다 빼고 순수 가격수익률로 신호 자체의 엣지만 검증.
- `test_hma_adx.py` — HMA cross에 ADX/DI 추세강도 필터 추가(횡보구간 크로스 무시).
- `test_htf_hma_filter.py` — 15분봉 신호에 1시간/4시간 상위타임프레임 HMA 정배열 필터 추가.
- `test_stage_sweep_htf.py` — 위에서 찾은 최적 조합(스퀴즈_avg 1.5x+ADX+1h HTF) 기준으로 Stage1~3 재스윕.
- `test_stage1_buf_verify.py` — staged_sl 버그 수정 후 Stage1 buffer 스윕이 정상 수렴하는지 재검증.
- `test_multi_coin_htf_stage.py` — XRP에서 튜닝한 조합을 BTC/ETH/SOL/DOGE로 그대로 검증(과최적화 체크).
- `test_1h_base_xrp.py` — 진입/청산 타임프레임 자체를 15분→1시간으로 전환(15분봉 노이즈 완화 목적).
- `test_vol_scaled_stages.py` — Stage1~3 고정%를 진입시점 BB폭 기반 변동성 스케일링으로 전환.
- `test_vol_scale_sweep_multicoin.py` — 변동성 스케일링 배수를 5개 코인 동시에 스윕(단일코인 과최적화 방지).
- `test_skip_stage1_multicoin.py` — Stage1(너무 이른 손익분기 락)이 노이즈 손절 원인인지 스킵 테스트.
- `test_atr_sizing_multicoin.py` — SL/TP 폭 기준을 BB폭 대신 ATR×배수로 전환(SL이 너무 타이트하다는 의심 검증).
- `test_squeeze_min_multicoin.py` — 스퀴즈 판정을 avg 대신 롤링최솟값(v2)으로 되돌리고 ADX+1h필터와 결합, 5코인.
- `test_confirm_multicoin.py` — "확인캔들+BO1.5+BB30+SL=min(avg폭,3%)" 조합의 5코인 일반화 검증.
- `test_current_live_xrp.py` — **최초로 실제 라이브 로직(`trading_service.py`)을 그대로 재현**하는 백테스트로 전환(이전까지는 별도 로직의 근사 버전이었음). 이후 모든 백테스트의 기반이 됨.

## 2026-08-12 — 진입직후 즉시손절 이슈 발견/수정, 필터 대안 검토

- `test_price_alignment_filter.py` — "HMA200/600 정배열만" vs "가격까지 완전정배열" 필터 비교
  → 후자는 거래수/PF/MDD 전부 악화(추격매수가 되어버림) → **기각**.
- `test_trade_distribution.py` — 거래별 수익률 분포 분석 → "쪼금쪼금형"이 아니라 상위 5%가
  전체 수익의 66%를 차지하는 "소수 대박형" 구조 확인.
- 이슈 수정: 진입 후 TP/SL 체크 대기시간 60초→15분(1캔들)로 확장, 커밋 `f70573c` 배포.
- 종합 기록: `2026-08-12_backtest_summary.md`, `STRATEGY_OVERVIEW.md` 최초 작성.

## 2026-08-14 — 방향판정/HMA갭 필터 실험

- `test_hma_direction_only.py` / `test_hma_direction_only_4coins.py` — 캔들몸통 대신
  HMA200/600 정배열 부호로만 방향 결정(`use_hma_direction_only`). XRP 거래수 454→878,
  승률 80.2%→86.3%, PF 2.00→2.49, MDD 54.56%→45.06% 대폭 개선 → 이후 "전략#2"로 채택.
- `test_fixed_notional_return.py` — 복리 수익률이 천문학적 숫자가 되어 직관이 어려워
  "항상 초기시드 75%×10x"로 고정하는 비복리 수익률 지표 도입.
- `test_hma_gap_threshold_sweep.py` / `_4coins.py` / `_livematch.py` — 정배열 갭이 너무
  작은(막 뒤집힌) 약한 신호를 거르는 최소 갭(%) 필터 스윕 → 실제 라이브 분기에 맞게 재검증.
- `test_hma_slope_filter.py` / `_1y.py` — HMA200 자체의 기울기가 신호 방향과 반대면 거르는
  필터 추가 검증(1년치로 재검증).
- `test_regime_exit.py` — **`use_regime_exit` 최초 도입**: 청산측 하드룰을 "가격vsHMA200
  단일선" 대신 "HMA200vs600 정배열 자체 반전"으로 교체(이후 08-17에 4코인 검증되어 배포).
- 상세 기록: `2026-08-14_full_test_log.md`, `2026-08-14_hma_gap_threshold.md`.

## 2026-08-15 — 빠른 브레이크아웃, 월별 분해

- `test_fast_breakout_xrp_1y.py` — 스퀴즈 상태 없이도 즉시 브레이크아웃 인식하는
  `use_fast_breakout` 도입(SOL 라이브 차트에서 스퀴즈 없이 갑자기 터진 케이스 놓침 발견).
- `test_price_vs_hma200_direction_xrp_1y.py` — 방향판정을 가격vsHMA200단일선으로 되돌리는
  대안(08-07 방식 복귀), fast_breakout과 조합 비교.
- `test_regime_direction_and_exit_xrp_1y.py` — `use_hma_direction_only` + `use_regime_exit`
  동시 적용 재확인(직전 08-14 테스트에서 진입단계 전환조건 겹침으로 PF0.35/MDD94.5% 대참사
  있었음 - 재현 여부 체크).
- 상세 기록: `2026-08-15_fast_breakout_test.md`, `2026-08-15_full_test_log.md`.

## 2026-08-16 — 청산로직 대개편 실험 (스탈exit/순수트레일/월별진단)

이 날 하루에만 17개 스크립트로 청산로직을 집중적으로 재설계.

- `test_regime_direction_monthly_xrp_1y.py` — "전략#2"의 월별 성과 분해(집중 vs 고른 분포 체크).
- `test_2candle_breakout_xrp_1y.py` / `_2x_xrp_1y.py` — 스퀴즈 상태머신을 버리고 "직전 캔들
  대비 폭 2.5x/2.0x" 단순 트리거로 대체 시도 → 신호가 너무 드물어 **기각**.
- `test_min_width_breakout_xrp_1y.py` — 롤링 30캔들 최소폭×2.0 기준 브레이크아웃(자기갱신형)
  → 비복리로는 좋았으나 복리 시뮬레이션 시 2025-10-11 부근 파산 발견.
- `test_price_alignment_entry_xrp_1y.py` — 가격정렬 필터를 `use_hma_direction_only` 경로
  에서도 추가 조건으로 걸 수 있게 확장(눌림목 진입 차단).
- `test_tight_exit_combo_xrp_1y.py` — Trend Follow Stop 청산 60건이 익절락 트리거(0.5%)도
  못 밟고 -$3,480 손실 낸 것 진단 → profit_lock_trigger 0.5%→0.2%, `stall_exit` 최초 도입,
  entry_sl_cap 3.5%→1.5% 3종 묶음 테스트.
  - `stall_exit`(정체 시 SL 조임)는 이후 08-16 저녁 `test_stallexit_fastbo_xrp_1y.py`에서
    "0.5% 피크 하나 기준"으로 정교화되어 이후 현재 라이브에 남아있는 형태로 정착.
- `test_minwidth_pricealign_xrp_1y.py` — min_width_breakout(파산 이력)에 가격정렬 필터를
  더해 파산이 막히는지 확인.
- `test_fast_breakout_pricealign_xrp_1y.py` / `_only_xrp_1y.py` / `_only_multi.py` /
  `_mixed_multi.py` — fast_breakout을 유일 트리거로 쓰는 안(XRP 단독은 PF2.18 좋았으나
  BTC/SOL은 PF<1로 실패) vs "스퀴즈 상태머신 주 + fast_breakout 보조" 혼합안(4코인 일반화
  성공) 비교 → **혼합안 채택**.
- `test_fast_breakout_sq05bo15_xrp_1y.py` — sq/bo를 코드 기본값(0.5/1.5)으로 되돌려 재검증
  (15분봉 확정 후).
- `test_fast_breakout_pricevshma200_xrp_1y.py` — 방향판정 방식을 다시 가격vsHMA200단일선으로
  바꿔 비교.
- `test_nofastbreakout_sol_1y.py` — SOL만 fast_breakout 없이(순수 조합) 테스트해 SOL이
  fast_breakout과 궁합이 안 맞는다는 가설 확인.
- `test_pure_regime_trail_xrp_1y.py` — 진입 후 SL/TP/익절락/스탈exit/단계전환 전부 끄고 오직
  "HMA정배열 반전 시에만 청산"하는 극단적 트레일 → PF0.56/MDD100% **대참사, 기각**(진입
  직후 무방비 상태가 문제).
- `test_regime_trail_after_profit_xrp_1y.py` — 위 방식의 문제를 고쳐 "피크수익 0.5% 도달
  전까지는 기존 청산스택 유지, 이후에만 순수 정배열 트레일로 전환" 절충안 테스트.

## 2026-08-17 — 청산스택 확정, profit_lock 비율 집중 튜닝, SuperTrend 계열 검토

- `test_current_live_4coin_1y.py` / `_2y.py` — 그날까지 확정된 라이브 풀 콤보(가격정렬+
  fast_breakout+stall_exit)를 4코인·1년/2년으로 첫 검증(BTC+38.7%/ETH+51.4%/XRP+56.0%/
  SOL+50.9%, PF 1.10~1.35 - 2년으로도 재현되어 단기효과 아님 확인).
- `test_candle_size_breakout_xrp_1y.py` — BB폭 대신 캔들 자체 크기(고가-저가) 기준 브레이크
  아웃 트리거 실험.
- `test_supertrend_xrp_1y.py` (및 `test_supertrend_tight_xrp_1y.py`,
  `test_supertrend_pure_1h_xrp.py`, `test_supertrend_direction_only_xrp_1y.py`) —
  SuperTrend 지표를 진입/청산/방향판정 각 단계에 대체 적용해봤으나 기본조합 대비 전부
  열세(PF 최고 0.89) → **SuperTrend 계열 전부 기각**, 현재 스택(HMA200/600) 유지.
- `test_candle_size_squeeze_xrp_1y.py` — 스퀴즈 판정 기준을 BB폭 대신 캔들크기로 교체 시도.
- **`test_regime_exit_xrp_1y.py` / `test_regime_exit_4coin_1y.py`** — `use_regime_exit`
  4코인 검증(승률63.2%→68.9%, PF1.35→1.36, HMA200 Break 청산 완전 소멸) → **채택,
  실거래 배포**. 상세: `2026-08-17_regime_exit_deploy.md`.
- `test_squeeze_bo_xrp_1y.py` / `test_squeeze_loosen_xrp_1y.py` /
  `test_breakout_loosen_xrp_1y.py` / `_4coin_1y.py` / `test_sq_bo14_xrp_1y.py` —
  스퀴즈/브레이크아웃 민감도(sq/bo) 개별 스윕. bo=1.4는 XRP는 개선됐으나 BTC 일반화 실패로
  **기각**, sq는 방향을 착각했다가(낮출수록 스퀴즈가 더 안 걸림) 정정.
- `test_trend_follow_trail_loosen_4coin_1y.py` — trend_follow 단계 HMA갭 트레일링을
  느슨하게(비율/버퍼 완화) 조정 시도.
- `test_profit_lock_ratio05_4coin_1y.py` / `_ratio07_4coin_1y.py` /
  `test_profit_lock_ratio10_4coin_1y.py` / `test_profit_lock_trigger10_4coin_1y.py` /
  `test_profit_lock_tiered_ratio_4coin_1y.py` / `test_profit_lock_ratio09_vs_10_4coin_1y.py`
  — **`profit_lock_ratio`(익절락 되돌림 허용폭) 집중 스윕**: 0.5(전부 악화)→0.7(개선폭
  작음)→0.85(당시 라이브)→1.0(전 코인 전지표 개선, 되돌림 0%로 즉시 고정) 순으로
  단조 개선 확인. 티어드(구간별 비율 차등)안도 시도했으나 단순 1.0 flat이 전부 이김
  → **ratio=1.0 채택, 배포**. 상세: `2026-08-17_profit_lock_ratio10_deploy.md`.
- `test_no_price_align_regime_exit_xrp_1y.py` — regime_exit 도입 후 진입측
  price_alignment_filter가 중복(불필요)인지 4-way 매트릭스로 확인.
- `test_compound_vs_fixed_4coin_1y.py` — 기존 "비복리" 지표 계산 방식이 방법론적으로
  틀렸음을 발견(레버리지/포지션사이징 무시한 단순 %합산) → 실제 복리 vs 고정명목($1,000/코인)
  비교로 교체.

## 2026-08-18 — 최소보유시간(min-hold) 실험 대량 진행 + 병렬 트랙(레버5/3시간홀드 채택)

이 날은 두 개의 병렬 실험 트랙이 진행됨: **Track A(낮 시간대)**는 sq/bo 및 hma_gap 미세조정,
**Track B(min-hold 계열, 낮~밤)**는 최소보유시간을 도입해 SL/TP 등 전 청산로직을 일정 시간
무시하는 실험으로, 최종적으로 "레버리지5x + 3시간 홀드 + 16%캡" 조합이 채택되어 실거래 배포됨.

**Track A**
- `test_current_live_1h_4coin_1y.py` — 캔들 타임프레임만 15분→1시간으로 교체해 비교(15분봉이
  더 우세, 15분봉 유지).
- `test_hard_tp_0p5_xrp_1y.py` — 기존(08-11) `hard_tp_pct` 파라미터로 무조건 0.5% 익절 강제.
- `test_fixed_tp_0p5_xrp_1y.py` — 위 파라미터가 `profit_lock_ratio=1.0` 때문에 데드코드였음을
  발견(결과가 baseline과 완전 동일) → 청산체크 순서를 앞당긴 `fixed_tp_pct`로 재구현.
- `test_bo_sweep_4coin_1y.py` — BREAKOUT_MULTIPLIER 1.1~1.5 스윕(라이브 1.6 대비).
- `test_hma_gap_1p5_4coin_1y.py` / `test_hma_gap_sweep_4coin_1y.py` /
  `test_hma_gap_sweep_low_4coin_1y.py` — 최소 정배열 갭(%) 임계값을 1.5%→1.1~1.4%→0.1~1.0%
  순으로 세분화 스윕(코인별 최적점이 갈려 뚜렷한 단일값 없음 확인).
- 종합: `2026-08-18_sq_bo_sweep.md`.

**Track B (min-hold 계열)**
- `test_sq09_bo16_xrp_1y.py` / `test_sq09_10_bo16_4coin_1y.py` / `test_sq10_bo20_4coin_1y.py`
  — sq를 0.9/1.0으로 느슨하게, bo도 2.0으로 올려보는 조합 실험.
- `test_min_hold_1h_xrp_1y.py` / `_4coin_1y.py` — **진입 후 1시간 동안 전 청산로직 무시**하는
  강제 보유창 도입(PF1.57→2.42, MDD 동일 유지 - XRP·4코인 전부 개선).
- `test_min_hold_2h_4coin_1y.py` / `test_min_hold_2h_mae_4coin_1y.py` — 2시간으로 확장, MAE(최대
  역행폭) 계측 추가해 보유창 동안의 청산방어 공백(10x 레버리지 청산위험 ~9~10%) 안전성 확인
  (945건 중 위험구간 진입 0건).
- `test_min_hold_3h_8p5sl_4coin_1y.py` / `test_min_hold_3h_7sl_4coin_1y.py`(Track2 재검증) —
  3시간 보유 + 파국적SL(8.5%→7.0%)만 살려두는 하이브리드 구조.
- `test_min_hold_2h_ratio08_4coin_1y.py`(Track2) / `test_min_hold_2h_7sl_4coin_1y.py`(Track2)
  — 2시간 보유로 축소하며 profit_lock_ratio/SL 재조정.
- `test_loosen4_no_hold_4coin_1y.py` — 보유창 대신 4개 청산조건을 전부 개별적으로 느슨하게
  만드는 대안 시도 → **PF<1, MDD 80~93%, 전 코인 대참사 → 기각**(보유창 방식이 안전함을 역설적으로 입증).
- `test_min_hold_2h_8p5sl_4coin_1y.py` / `test_min_hold_4h_8p5sl_4coin_1y.py`(Track1) —
  안전한 하이브리드 구조로 복귀 후 보유시간 2h→4h 확장 재검증.
- `test_pure_pct_trail_4coin_1y.py` — 4개 청산조건 전부를 단일 % 트레일(3.0%)로 완전 대체 시도
  → **PF<1, MDD 97~100% 대참사, 기각**(손절조건까지 같이 없어져 실패 포지션이 -3%까지 방치됨).
- `test_trend_follow_pct_trail_4coin_1y.py` — 위 실패를 고쳐 stall_exit/regime_exit(손실차단용)는
  유지하고 익절 관련 2개(profit_lock/HMA갭트레일)만 3.0% 단일트레일로 교체.
- `test_tf_trail_floor_4coin_1y.py` — 3% 고정폭이 작은 피크에서 진입가 아래로 내려가는 결함
  발견 → 1.5% 트레일 + 손익분기 플로어 추가.
- `test_tf_trail_floor_wide_4coin_1y.py` — 1.5%가 너무 타이트(보유시간 1.6~3.6h로 급감, PF
  0.41~0.75)해서 6.0%로 확장 재시도.
- `test_min_hold_3h_lev5_16sl_4coin_1y.py`(Track2) — **레버리지 10x→5x로 전환**(파국적SL 상한을
  8%→16%로 완화 가능), 3시간 보유 구조 재검증 → 최종 이 조합이 유력해짐.
- 최종 채택: 레버리지5x + 3시간 홀드(파국적SL 16%만 체크) + sq0.7/bo1.6 유지 →
  **실거래 배포**. 상세: `2026-08-18_leverage5_3h_hold_16sl_deploy.md`.

## 2026-08-19 — sq0.85/bo1.3 진입완화 + 레버리지10x·대장주15종 화이트리스트 전환

- `test_sq085_bo13_lev5_16sl_4coin_1y.py`(Track2) — 스퀴즈 없이 서서히 오르는 추세를 놓치지
  않기 위해 진입 임계값을 sq0.85/bo1.3으로 완화, 08-18 채택 구조(레버5/3시간홀드/16%SL)에
  적용해 실제 배포수치와 비교(BTC/ETH/XRP/SOL 전 코인 개선).
- `test_sq085_bo13_lev10_1h_85sl_4coin_1y.py`(Track2) — 사용자가 빠른 진입을 원해 레버리지
  10x + 1시간 홀드 + 8.5%SL 조합으로 재시도 → 결과 저하(PF1.46~1.65, MDD 33.6~69.6%) →
  1시간 홀드가 승리거래를 너무 일찍 끊는다는 가설 제기.
- `test_sq085_bo13_lev10_nohold_4coin_1y.py`(Track2) — 위 가설 검증을 위해 홀드윈도우를 아예
  제거(순수 라이브로직) → 개선 확인.
- **최종 채택**: sq0.85/bo1.3 + 레버리지10x + 홀드윈도우 완전 제거 + **대장주 15종 화이트리스트**
  전환(기존 4종에서 확대) → 실거래 배포. 상세: `2026-08-19_major_whitelist_lev10_nohold_deploy.md`,
  `2026-08-19_sq085_bo13_deploy.md`.

## 2026-08-21 — profit_lock_ratio 재조정

- `profit_lock_ratio` 1.0 → 0.8로 하향(상승장에서 트레일링 여유를 좀 더 주는 방향) 실거래 반영.
  상세: `2026-08-21_profit_lock_ratio08_deploy.md`.

## 2026-09-05 — 초기SL캡/실거래 정합성 검증 + BTC 모멘텀 게이트 도입·lookback 튜닝

- `test_sl_cap_mae_4coin_1y.py` — 초기 SL캡(3.5%→1.5%/1.0%)을 조이면 결국 회복했을 거래를
  너무 일찍 끊는 게 아닌지 MAE 계측 + 실제 재시뮬레이션으로 검증(경과 파라미터 정정: `profit_lock_ratio`
  1.0→0.8, 재진입 쿨다운 30분→1시간도 이 시점에 함께 재확인).
- `test_live_match_15coin_17d.py` — 백테스트 엔진이 **실제 라이브(bot1, paper) 거래기록과
  얼마나 일치하는지** 검증 - bot1이 실제 거래한 15종·17일을 그대로 재현해 실제 `trades.json`
  (610건, 승률70.8%, PF1.12, +$998.58)과 대조.
- `test_btc_momentum_gate_15coin_17d.py` — **BTC 모멘텀 게이트 최초 아이디어 검증**: BTC가
  직전 4시간 동안 ±1% 이상 움직였을 때만 전 코인 신규진입 허용. 17일·15종 기준 게이트없음
  PF1.17→게이트있음 PF2.60로 개선되었으나 표본이 작아(158건) 우연 가능성 우려.
- `test_btc_momentum_gate_4coin_1y.py` — 표본 확대를 위해 BTC/ETH/XRP/SOL 1년치로 재검증,
  4종목 전부 예외없이 개선(승률62.4%→74.7%, PF1.08→1.98, MDD69.2%→30.3%, 수익
  +$7,263.88→+$100,100.65) → **채택, 실거래 배포**(lookback 4시간). 상세:
  `2026-09-05_btc_momentum_gate_deploy.md`.
- `test_btc_gate_lookback_sweep_4coin_1y.py` — 배포 후 "lookback이 짧을수록/길수록 어떻게
  달라지나" 궁금증 해소용 스윕(1h/4h/12h/24h, 4코인·1년, 순수 조사용). 결과: 1시간이 전
  지표 최우수, 24시간(사용자 원안)이 최하위(게이트가 56%나 열려있어 필터 효과 희석).
- `test_btc_gate_1h_lookback_15coin_1y.py` / `test_btc_gate_4h_lookback_15coin_1y.py` —
  스윕에서 1위였던 1시간 lookback을 표본 우려 해소를 위해 **bot1 실거래 15종·1년 전체**로
  재검증, 당시 라이브였던 4시간과 동일조건 직접 비교(1시간이 승률/PF/MDD/수익 전부 우세,
  거래수는 -46%) → **1시간으로 축소, 실거래 배포**. 상세: `2026-09-05_btc_gate_lookback_1h_deploy.md`.
- `test_btc_gate_2h_lookback_15coin_1y.py` — 1시간/4시간 사이 중간지점(거래빈도와 필터
  엄격도의 절충점) 참고용 검증. 총수익은 최고치(+$428,978.89)를 기록했으나 MDD(31.2%)가
  4시간 수준에 가까워 채택하지 않고 1시간을 유지.

---

## 배포로 이어진 주요 변경 정리 (연대순)

| 날짜 | 변경 | 문서 |
|---|---|---|
| 2026-08-12 | 진입 직후 TP/SL 체크 대기 60초→15분 | `STRATEGY_OVERVIEW.md` §5 |
| 2026-08-17 | 0단계 하드청산: 가격vsHMA200 → 정배열(regime) 반전 | `2026-08-17_regime_exit_deploy.md` |
| 2026-08-17 | profit_lock_ratio 0.85 → 1.0 | `2026-08-17_profit_lock_ratio10_deploy.md` |
| 2026-08-18 | 레버리지10→5x + 진입후 3시간 보유창(파국적SL 16%만 체크) | `2026-08-18_leverage5_3h_hold_16sl_deploy.md` |
| 2026-08-19 | sq0.7/bo1.6 → sq0.85/bo1.3 진입완화 | `2026-08-19_sq085_bo13_deploy.md` |
| 2026-08-19 | 대장주 15종 화이트리스트 + 레버리지 10x 복귀 + 홀드윈도우 제거 | `2026-08-19_major_whitelist_lev10_nohold_deploy.md` |
| 2026-08-21 | profit_lock_ratio 1.0 → 0.8 | `2026-08-21_profit_lock_ratio08_deploy.md` |
| 2026-09-05 | BTC 모멘텀 게이트 도입 (조용한 장 신규진입 차단, lookback 4시간) | `2026-09-05_btc_momentum_gate_deploy.md` |
| 2026-09-05 | BTC 게이트 lookback 4시간 → 1시간 | `2026-09-05_btc_gate_lookback_1h_deploy.md` |

## 조사했으나 기각된 주요 대안 (배포 안 됨)

- SuperTrend 계열 진입/청산/방향판정 전체 (2026-08-17) — 기본 HMA200/600 스택 대비 전부 열세.
- 가격vsHMA200 완전정배열 진입필터 (2026-08-12) — 추격매수가 되어 PF 악화.
- 순수 % 트레일로 전 청산조건 대체 (2026-08-16/18, `pure_pct_trail`) — 손절조건까지 사라져
  MDD 97~100% 대참사.
- 4개 청산조건 개별 느슨화 + 홀드윈도우 없음 (2026-08-18, `loosen4_no_hold`) — PF<1, MDD 80~93%.
- 레버리지10x + 1시간 홀드 + 8.5%SL (2026-08-19) — 3시간/레버5 대비 저하, 홀드가 너무 짧음.
- 2시간(8캔들) BTC게이트 lookback (2026-09-05) — 총수익 최고지만 MDD가 1시간만큼 개선 안 됨.
