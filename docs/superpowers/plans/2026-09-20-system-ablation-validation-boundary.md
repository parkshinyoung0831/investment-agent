# System ablation validation boundary — Implementation Plan

**Goal:** 운영 Trading 알고리즘을 그대로 재생해 검증하는 ablation을 일반 Research 계산과 구분된 `research/system_validation` 경계로 옮기고, 허용 import를 실제 7개로 고정한다.

**Boundary:** Trading 알고리즘, variant, risk 수치, PIT/replay cutoff, 운영 원장 write 차단, CLI 경로와 출력 형식을 바꾸지 않는다. 일반 Research→Trading import의 광범위한 예외를 만들지 않는다.

### Task 1 — 실제 호출자와 검증 성격 확인 (완료)

이전 `research/ablation.py`는 운영 `AlphaPolicy`, System target/engine/accounting/store를 같은 historical replay에 사용한다. 일반 feature 계산이 아닌 production 알고리즘 검증이다. production caller는 `research.commands.system_ablation` 한 곳이고, Trading system의 격리 guard와 Research ablation tests가 기존 경로를 참조한다. CLI module path는 유지한다.

### Task 2 — 실패 계약과 직접 이동 (완료)

test owner import와 pending 7쌍 제거로 RED(새 모듈 부재·위반 7건)를 확인한다. 본체를 `research.system_validation.ablation`으로 이동하고 CLI·tests·source 설명을 직접 이관한다. 이전 module alias는 두지 않는다. Architecture allowance는 해당 파일의 7개 실제 Trading imports에만 적용하고, 새 폴더 파일에 임시 위반을 주입해 guard 실패를 검증한다.

### Task 3 — 통합 검증과 인계 (완료)

ablation/Trading system/architecture/workflow/docs 96개가 통과했다. 전체 offline suite 3,034개는 기존과 같은 선택적 `lightgbm`/`xgboost` 미설치 오류 4개·skip 1개뿐이다. CLI help/import, legacy caller·diff 검색을 확인하고 결과·남은 debt를 진행 원장에 기록한다.
