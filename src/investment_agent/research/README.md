# Research — PIT feature·dataset·모델·평가·승격

`investment_agent.research`는 **"과거 그 시점에 실제로 알 수 있었던 것만"** 으로 학습하고
평가하는 계층이다. 저장소는 Supabase가 아니라 로컬 DuckDB와 Parquet이다 — 연구 산출물은
언제든 다시 만들 수 있고, 다시 만들 수 없는 것은 **무엇으로 만들었는지의 기록**뿐이기
때문이다.

`trading`은 이 계층의 결과를 읽지만, 이 계층은 `trading`을 부르지 않는다. *(테스트 강제)*

## 흐름

```text
market·fundamentals·macro (Supabase)
  → features   RSI·MACD 등 일간 지표를 PIT로 계산
  → datasets   feature + label을 불변 dataset으로 고정(hash)
  → training   baseline·challenger 학습
  → evaluation OOS·walk-forward·DSR·거래비용
  → promotion  증거 없으면 승격 없음
       ↓
  strategies   위 축과 별개의 월간 자산배분 6종
```

| 하위 패키지 | 하는 일 |
|---|---|
| `features/` | 일간 기술지표 ETL과 PIT feature layer |
| `datasets/` | 불변 dataset 조립(내용 해시로 고정) |
| `training/` | 학습과 walk-forward 평가의 공통 호출 경계 |
| `models/` | 선택 의존성을 지연 로드하는 numeric model 진입점 |
| `evaluation/` | 연구 metric과 OOS 안정성 |
| `backtest/` | 목표 비중을 가격 이벤트 위에서 재생하는 결정론적 백테스트 |
| `rl/` | PIT feature snapshot을 쓰는 RL·정책 학습 |
| `promotion/` | challenger 승격 판정 |
| `system_validation/` | 동일 운영 엔진으로 과거 구간을 재현한다 — 변형 비교(`ablation.py`), System 승격 증거(`evaluations.py`) |
| `valuation/` | PIT 밸류에이션 계약과 입력 조립 |
| `strategies/` | 팩터/룰 기반 자산배분 6종 → [README](strategies/README.md) |
| `storage/` | 로컬 DuckDB·Parquet 경계(`ResearchStore`) |

## 저장 계약

대용량 행은 **Parquet가 소유하고**, DuckDB에는 작은 catalog와 재현 가능한 metadata만 둔다.
여덟 표는 세 묶음이고 하는 일이 다르다 — 숫자만 보고 합치면 기능이 준다.

| 묶음 | 표 | 무엇을 지키나 |
|---|---|---|
| Parquet 뿌리 catalog | `feature_sets`, `dataset_runs` | "그 parquet 뿌리가 어디고 얼마나 최신인가" |
| 연구 lineage | `datasets` → `experiments` → `models` → `backtests` | 어떤 데이터로 무엇을 학습해 어떻게 평가했나 |
| 전략 연구 | `strategy_runs`, `strategy_allocations` | 월간 배분 파이프라인의 관계형 계약 |

단일 선언은 `db/duckdb/research/v1/*.sql`이다. 기본 경로는
`data/local/research/research.duckdb`이며 커밋하지 않는다.

## 실행

```bash
python -m investment_agent.research.commands.build_features
python -m investment_agent.research.commands.build_labels
python -m investment_agent.research.commands.build_training_samples
python -m investment_agent.research.commands.train_baseline
python -m investment_agent.operations.commands.evaluate_decisions
python -m investment_agent.research.commands.export_dataset
python -m investment_agent.research.commands.backfill_research_history --start 2023-01-06 --end 2025-12-31 --every-days 7 --audit-only
python -m investment_agent.research.commands.backfill_research_history --start 2023-01-06 --end 2025-12-31 --every-days 7
python -m investment_agent.operations.commands.system_ablation --start 2025-01-01 --end 2025-12-31
python -m investment_agent.research.strategies.etl            # 월간 전략 배분
```

수동 승격 게이트(`promotion/gate.py`)는 artifact별 `portfolio_evaluations` 행만 증거로 읽는다. System artifact의
그 행은 `system_evaluations`가 만든다 — 운영 정책의 재현은 `backtest`·연도별 `walk_forward`로(과거 LLM 논지가
없어 `thesis_replayed=false`로 적는다), artifact의 첫 목표 이후 운영 NAV는 `out_of_sample`(paper 승인 뒤는
`paper`)로. 재현 시점 멤버 중 feature가 없어 빠진 비율이 5%를 넘으면 생존 편향 사고로 센다. 하네스
`system_evaluation` 잡이 7일마다 이것과 factor IC(`factor_research`, 5·20·60·120일)를 돈다.

ML 학습은 학습 구간에서 값이 변하지 않는 열을 입력에서 뺀다. 과거 재현 표본은 macro·technical·revision
열이 시점 기준으로 비어 있어 상수인데 운영에서는 값이 들어온다 — artifact의 `feature_names`는 모델이 실제로
받은 열이고, 뺀 열은 `excluded_constant_features`에 남는다.

RL 후보 재학습(`continuous_retrain`)은 판단 경로가 쓰지 않아 하네스 정기 실행에서 뺐고 수동으로 돌린다.
새 성숙 비중첩 구간이 2개 미만이면 학습하지 않는다.

과거 재현 백필은 원격 재무·컨센서스·주식수·세그먼트를 날짜마다 일괄 조회하고, 종목별 계산은 그
결과를 재사용한다. 날짜 결과는 Parquet에 한 번만 원자 저장한다. 날짜별 manifest가 실제 snapshot과
영구 불가 ticker를 기록하므로 중단 후에는 누락 ticker만 재개한다. 먼저 `--audit-only`로 완결성을
확인할 수 있으며, 이 모드는 어떤 연구 데이터도 쓰지 않는다. 가격이 없어 '영구 불가'였던 과거 멤버의
가격을 뒤늦게 백필했으면 `--retry-unavailable`로 그 종목만 다시 계산한다 — 그러지 않으면 지수를 나간
종목이 재현에서 계속 빠진다(생존 편향).

`build_training_samples`는 `training_sample_runs` 로컬 매니페스트에 기준일별 feature 입력 해시,
확정 label ID, 비용 모델의 결합 서명을 기록한다. 같은 서명은 표본 재계산과 Parquet 쓰기를 모두
건너뛴다. feature 입력·label·비용 모델이 바뀌면 영향을 받은 기준일만 다시 만든다. 매니페스트는
ResearchStore의 로컬 데이터셋이므로 Supabase 스키마를 바꾸지 않는다. 반복 확인은 feature·label
payload 전체를 복원하지 않고 서명에 필요한 scalar만 DuckDB에서 읽으며, 표본 본문은 변경된 기준일에만
다시 읽는다.

무거운 의존성(`lightgbm`, `stable-baselines3`, `pyqlib`)은 **호출 시점에 지연 import**한다.
`research`를 import하는 것만으로 그것들이 설치돼 있어야 하면 안 된다.

## 조용히 틀리는 것

- **look-ahead.** 공시일(`filed_at`) 이후에 알게 된 값을 그 이전 시점의 feature로 쓰기.
  가격은 공시일보다 **엄격히 이전**이어야 한다.
- **survivorship.** 오늘의 tracked 목록으로 과거를 재현하기. membership snapshot은
  "오늘 무엇을 수집할까"의 gate이지 과거 universe가 아니다.
- **부분 TTM.** 3분기 합을 4분기 합처럼 쓰기. 한 분기라도 비면 TTM을 만들지 않는다.
- **증거 없는 승격.** OOS·walk-forward·paper 기록 없이 stage를 올리기.
- 학습 산출물을 Supabase에 쓰기. 연구 저장소는 로컬이다.

## 고칠 때 함께 볼 곳

- 새 feature → `features/`. feature·label에는 버전 컬럼이 없다 — 컬럼 구성이 바뀌면 `FeatureLayer.definition_hash`가 달라져 backfill이 다시 만들고, 값 정의만 바뀌면(컬럼은 그대로) 저장된 feature snapshot·label·학습 표본을 지우고 다시 적재한다. 옛 값을 새 값과 섞지 않는 유일한 방법이다
- 표를 늘린다 → `db/duckdb/research/v1/*.sql`의 머리주석(세 묶음 구분)이 기준
- 화면 노출 → `reporting/readers/research.py`
- 3축 이름(`stage`/`execution_mode`/`source_kind`) → CLAUDE.md 규칙 14
