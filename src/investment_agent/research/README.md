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
python -m investment_agent.research.commands.evaluate
python -m investment_agent.research.commands.export_dataset
python -m investment_agent.research.strategies.etl            # 월간 전략 배분
```

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

- 새 feature → `features/`, 그리고 그 feature를 쓰는 dataset의 `feature_version`
- 표를 늘린다 → `db/duckdb/research/v1/*.sql`의 머리주석(세 묶음 구분)이 기준
- 화면 노출 → `reporting/readers/research.py`
- 3축 이름(`stage`/`execution_mode`/`source_kind`) → CLAUDE.md 규칙 14
