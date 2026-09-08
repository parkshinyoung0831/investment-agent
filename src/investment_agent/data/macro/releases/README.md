# Macro 경제발표

**원자료·일정·예상값의 변경만 저장한다. 계산한 실제값은 다시 저장하지 않는다.**
시장 지표와 고정 30개 발표 지표를 하나의 `macro` owner 아래 versioned 표로 관리한다.
운영용 read model은 [v1 reporting SQL](../../../../../db/postgres/v1/90_reporting.sql)이 소유한다.
DB 초기화·재수집은 모든 writer/reader 전환과 전체 테스트가 끝난 뒤 별도 승인으로 진행한다.

## 키와 저장 단위

| 객체 | 저장하는 것 | 기본키 |
|---|---|---|
| `series` | 30개 지표의 이름·국가·분류·주기·원자료 단위·시간대 | `series_key` (물리 키), `series_code` = `US_CPI` |
| `measures` | 46개 표시/계산 정의: 식·단위·비교기간·집계 방법 | `measure_id` = `US_CPI.MOM` |
| `sources` | 출처 문자열과 표시 우선순위 | 작은 정수 `source_id`; `code` UNIQUE |
| `release_events` | 지표와 기준기간의 발표 식별자 | **`(series_key, ref_period)`** |
| `release_schedule_versions` | 일정·정밀도·취소 상태의 변경 | `(series_id, ref_period, collected_at)` |
| `economic_observations` | 경제 원자료 값과 빈티지/수집 시각 | `(series_key, observation_date, vintage_at, available_at)` |
| `forecast_snapshots` | 같은 measure·예상 종류·출처의 예상값 변경 | 지표·기간·measure·종류·출처·두 시각의 복합키 |

`release_id`는 없다. 발표시각이 바뀌어도 `US_CPI:2026-07-01`이라는 화면·알림 키는 유지된다.
월간 기준기간은 그달 1일, 분기는 1·4·7·10월 1일이다. 주간/비정기는 제공처 계약의 기준일이다.
`measure_id`는 임의 숫자가 아니라 사람이 읽는 이름이다. `US_CPI`만 쓰면 지수·MoM·YoY를
구별하지 못하므로 `.MOM` 같은 의미가 필요하다. 별도 `code` 열은 저장하지 않는다.
버전 표에는 의미 없는 정수 ID를 두지 않는다. 같은 흐름의 정확한 시각이 버전을 식별하며,
동일한 두 시각에 서로 다른 상태가 들어오면 순서를 추측하지 않고 거부한다.

ICS UID도 자연키에서 계산하며 이를 저장하는 열은 없다. 같은 지표·기준기간은
일정 변경과 무관하게 동일한 UID를 사용한다.

수집 제공처·API 코드·배율·일정 규칙·라이선스 제약은 [series_config.json](series_config.json)에
한 번만 둔다. 값 행에 단위, provider code, provenance JSON, fingerprint, 처리 상태를 반복하지 않는다.
화면 대표값은 `measures.is_primary`, 자동 모델 대상은 설정의 `forecast_measure_id`로 분리한다.
지표·measure의 식/기준단위/시간대 변경은 과거 의미를 바꾸므로 일반 UPDATE로 허용하지 않는다.

## 변경과 시간

| 열 | 의미 |
|---|---|
| `effective_at` | 원자료·예상값을 원출처가 공개한 시각. 불명확하면 최초 수집 시각 |
| `collected_at` | 이 시스템이 실제로 확보한 시각. 과거 백필에서도 오늘 수집했다면 오늘 |
| `time_precision` | `exact`, `date_only`, `collector_seen` |

일정은 현재 공급자에서 출처 유효시각과 수집시각이 항상 같으므로 `collected_at` 하나만 저장한다.
값의 `time_precision` 대신 `schedule_precision`을 둔다.
`exact`/`estimated`/`rule`/`date_only`의 감시창은 각각 2/6/12/36시간이다.
날짜만 알려진 일정의 현지 정오는 달력 저장 기준점이며 실제 발표시각이 아니다.
ALFRED 빈티지의 날짜 정밀도와 실제 수집시각도 구별한다. 정확한 장중 발표시각으로 해석하지 않는다.
PostgreSQL `timestamptz`는 선언 정밀도와 무관하게 8바이트다. 분 단위로 잘라도 용량은 줄지 않고
같은 분 안의 변경 순서만 잃으므로 원래 시각을 저장하고 화면에서만 짧게 표시한다.

예상값이 `0.2 → 0.3 → 0.2`로 바뀌면 **3개 상태를 보존**한다. `0.2 → 0.2` 재확인은
DB 쓰기 없이 끝낸다. 정밀도가 달라지면 새 상태로 보존한다.
이 비교는 같은 기준기간 안에서만 한다. 6월과 7월의 같은 숫자는 각각 보존한다.
현재 연결된 출처가 공식 정정 키를 한 건도 제공하지 않으므로 비어 있던 정정 키 열은 저장하지 않는다.
두 시각이 모두 같은데 값이 충돌하면 순서를 추측하지 않고 오류로 처리한다.
RPC 안에서 지표/기간/예상 출처별 잠금을 잡아 동시 쓰기의 중복을 방지한다.
하루 한 번으로 제한하는 중복 방지 조건은 없다. 실제 포착 범위는 제공처와 polling 주기에 달려 있다.

예상값 `NULL`은 제공처가 명시적으로 철회했을 때만 적재한다. 통신 실패나 미지원은 철회가 아니다.
최신 철회를 이전 숫자로 채우지 않는다. 출처가 여러 개이면 `sources.priority`, `code` 순으로 고른다.
역사 재구성 모델·GDPNow archive는 실시간 수집 출처보다 낮은 우선순위를 쓴다.

## 저장과 계산 예시

CPI 6월 원지수 100, 7월 102만 `observation_versions`에 넣으면 `US_CPI.MOM`은 `(102/100-1)×100=2%`다.
전년 7월 값이 98이면 `US_CPI.YOY`는 `(102/98-1)×100`으로 계산한다.
2%·YoY를 `actuals`라는 별도 표에 복제하지 않는다.

6월 지수가 나중에 101로 개정되면 6월 원자료 변경 한 행만 추가한다. 7월 최신 MoM은 약 0.9901%가 되고,
이전 입력으로 얻은 최초 계산값 2%는 시각 자연키 이력에서 재현한다.
10월 원자료가 빠졌다면 11월 MoM에 9월 값을 대신 쓰지 않는다. 비교값이 없으면 NULL/행 없음이다.
YoY는 정확히 전년동월을 찾으므로 중간 누락 월이 있어도 12번째 이전 관측치로 밀리지 않는다.

미국 GDP의 원자료는 이미 공식 전기비 연율이므로 `level` 변환으로 그대로 읽고 다시 연율화하지 않는다.
한국 GDP 역시 현재 계약은 공식 전기비이며 원 GDP 수준이 아니다.
따라서 이 두 비율만으로 연간 실질 GDP 수준·연간 성장률을 만들어 낼 수는 없다.

## reporting read model

| 읽기 객체 | 역할 |
|---|---|
| `reporting.macro_series` | macro 지표 master와 source 표시 정보 |
| `reporting.macro_observations` | 지표·기준기간별 최신 원자료 |
| `reporting.macro_release_summary` | 발표별 최초/최신 실제값·현재/발표 전 예상값·오차 |
| `reporting.macro_release_forecasts` | 출처별 예상값 변화·이전 값·변경폭 |
| `reporting.macro_release_actuals` | 자연키별 실제값·개정 이력 |
| `reporting.macro_measures` | 명시적 measure master |

모든 뷰는 `security_invoker=true`이며 데이터를 별도로 복제하지 않는다. 앱 접근은 service role로 제한한다.
원자료/일정/예상값 검색에는 복합 인덱스 하나씩을 둔다. PK·출처 코드 UNIQUE·대표 measure UNIQUE를
포함해 총 9개 인덱스다. 세 이력표의 자연 기본키가 최신 조회도 담당하므로 별도 중복 인덱스를 두지 않는다.

measure 변환은 raw version을 기준으로 계산하며 모든 숫자에 같은 SUM/AVG를 적용하지 않는다.

- 월간 수출 흐름: 12개월을 모두 확보했을 때만 연간 SUM. 2개월만 있으면 연간 값은 NULL이며 개수는 2/12다.
- 실업률·지수·연율 판매량: 정의된 평균. 부분 기간이면 `is_complete=false`다.
- 주간 재고·유동성 수준: 월/연 마지막 관측값. 예상 관측 개수를 확정하지 못하면 완결로 표시하지 않는다.
- MoM·YoY·전기비: 무조건 합하거나 평균 내지 않는다. 지정된 집계가 없으면 집계 행도 없다.

## 시점과 발표 오차

AI의 과거 시점 `T`는 **`effective_at <= T AND collected_at <= T`**를 만족하는 자료만 쓴다.
예를 들어 2020년 빈티지를 2026년에 가져와도 2020년의 시스템 백테스트 입력에는 들어가지 않는다.
`basis='source'`는 지금 확보한 빈티지로 원출처의 수정 이력을 재구성하고,
`basis='system'`은 실제로 이 시스템이 알게 된 순서를 재구성한다. 두 결과는 다를 수 있다.
더 오래된 빈티지를 나중에 확보하면 source 기준 최초값이 보완될 수 있다. 같은 출처 시각의
여러 수집 상태는 source 조회에서 cutoff까지 확보한 마지막 상태를 사용한다. 날짜 정밀도만으로
장중 최초 발표를 확정하지 않는다. 고정 cutoff의 시스템 PIT와 이 재구성을 구별해야 한다.
예상값은 생성일이 조회 lookback보다 오래돼도 해당 발표에 여전히 유효하면 읽는다.
예상값이 없는 미래 일정도 AI 이벤트 위험 근거에 포함한다.

`survey`, `nowcast`, `own_model`을 서로 대체하지 않는다. 발표 오차는 최초 보관 실제값과
발표 전까지 실제 수집한 마지막 예상값을 비교한다. 보수적인 마감 기준은 예정시각과 최초 관측시각 중 이른 쪽이다.
발표 후 들어온 예상값이나 최신 정정 실제값으로 과거의 surprise를 바꾸지 않는다.
`revision = latest_actual_value - first_actual_value`다.

원지수로 계산한 비율은 공식 헤드라인의 계절조정·반올림 정의와 다를 수 있다.
이 경우 파생 비율의 시장 surprise를 비운다. 저장 열 없이 `transform='level'`인 공식 수준·비율만
동일 measure 예상값과 비교하도록 뷰가 계산한다.
현재 공개 빈티지가 없는 지표는 ‘최초 보관값’이지 ‘공식 최초 발표값’이라고 보장할 수 없다.

## 실행과 소비자

```bash
python -m investment_agent.data.macro.commands.econ_calendar_daily --horizon-days 120
python -m investment_agent.operations.commands.econ_calendar_watch_releases --poll-attempts 4 --poll-interval-seconds 20 --notify
python -m investment_agent.data.macro.commands.econ_calendar_revision_audit --days 3650
python -m investment_agent.data.macro.commands.econ_calendar_backfill --backfill-from 2016-01-01
python -m investment_agent.data.macro.commands.econ_calendar_backfill --backfill-from 2024-01-01 --series EIA_CRUDE_OIL_INVENTORIES
python -m investment_agent.data.macro.commands.econ_calendar_publish_ics
python -m investment_agent.data.macro.commands.econ_calendar_validate --require-data
```

Daily는 최근 범위와 계산에 필요한 비교기간까지 함께 확인한다. 예를 들어 YoY의 비교월이
이번 발표 때 개정되면 원자료 변경도 함께 들어온다. 더 넓은 빈티지 감사·10년 백필은 별도 실행이다.
Watcher는 해당 발표의 기준기간뿐 아니라 필요한 기저기간도 저장하되 알림 대상만 좁힌다.
백필/수정 감사는 직접 알림을 발생시키지 않는다.
백필은 공식 최초 발표일을 먼저 적재하고 달력 후보로 빈 기간만 채워 임시 추정 버전을 늘리지 않는다.
ECOS 과거 이력은 전체 페이지를 읽으며, 첫 1,000행에서 잘리거나 페이지가 겹치면 정상 적재로 처리하지 않는다.
과거 최초 일정은 후속 GDP 개정 발표로 바뀌지 않도록 일반 동기화에서 동결한다.
ALFRED 최초 발표 복원과 취소 외의 과거 일정 정정은 별도 감사 대상으로 다룬다.

대시보드는 기간 조회·지표별 조회·자연키 상세 조회를 분리한다. 그래프는 최신값, 발표 비교는 최초값이다.
ICS는 일정 연기에도 UID를 유지하고 취소 상태를 내보낸다.
Discord 성공 기록은 **`notifications.outbox`·`notifications.deliveries`**에 보관한다. macro 표에 발송 플래그를 두지 않는다.
보내기 실패는 적재를 되돌리지 않으며 다음 notifier 실행이 재시도한다. 여러 배치 중 성공한 배치만 기록한다.
Discord 전송과 DB 기록은 하나의 트랜잭션이 아니므로 ‘전송 성공 후 기록 직전 장애’의 중복 가능성은 남는다.

## 현재 데이터 공급 범위

30개/46개 정의는 [db/postgres/v1/40_macro.sql](../../../../../db/postgres/v1/40_macro.sql), 제공처 계약은
[series_config.json](series_config.json)과 [SOURCE_CONTRACT.md](SOURCE_CONTRACT.md)를 참조한다.
ISM 2개는 라이선스가 확인된 자동 수집 경로가 없어 미지원이다. 승인된 제공처가
확보되기 전에는 대체값이나 임의의 과거 consensus를 생성하지 않는다.
현재 자동 예상값 수집은 GDPNow와 설정된 `forecast_measure_id`의 자체 baseline이다.
대표 실제값과 모델 대상이 다르면 서로 빼지 않고 상세 이력과 AI 스냅샷에 각각 제공한다.
허가된 Survey 공급자는 아직 없으며, 없는 과거 consensus를 생성하지 않는다.

## 검증과 운영 전환

빈 DB 선언 순서는 공통 extension과 domain schema를 모두 세운 뒤
`db/postgres/v1/90_reporting.sql` view를 마지막에 적용하는 방식이다.
`scripts/postgres_schema_layout.py`와 `scripts/db_bootstrap.py`가 이 순서를 단일 기준으로
사용한다. 알림 outbox는 `data/local/runtime/runtime.sqlite3`가 소유하므로 PostgreSQL
notifications SQL은 적용하지 않는다. 운영 DB 변경은 이 작업에서 실행하지 않는다.

```bash
python -m unittest discover -s tests -t .
# ECON_TEST_DB_URL을 빈 임시 PostgreSQL로 지정한 경우에만 실행; 모든 생성물은 롤백
python -m unittest discover -s tests -t ./investment_agent/data/macro/releases -p "test_*.py"
```

SQL 회귀 사례는 v1 macro 스키마 테스트와 도메인 단위 테스트가 소유한다.
새 자료의 적재 검증·용량·조회·한계와 적용 이력은 선언 SQL과 도메인 테스트가 현재 모양의
단일 기준이다.
운영 적용 전 코드·DB 버전을 맞추고 백업·정비 보류를 확인한다. 검증이 끝나기 전 하네스를 재개하지 않는다.
