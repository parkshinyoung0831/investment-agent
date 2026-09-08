# Universe v1

`investment_agent.data.universe`는 회사 identity, 거래 증권, point-in-time
S&P 500 membership을 소유한다. 회사 사실은 `entities(cik)`에 한 번만 저장하고,
ticker는 `securities(security_id)`의 현재 표기로 다룬다.

### 30초 예시: Alphabet

SEC exchange master의 회사명은 새 entity를 **처음 만들 때만 쓰는 seed**다. 이후
공식 metadata는 submissions가 갱신하고, `is_active_listing`은 현재 SEC master에
관측된 상장 여부를 뜻한다.

## 저장 계약

| 사실 | v1 표 |
|---|---|
| SEC 등록인과 SIC metadata | `universe.entities` |
| 상장 증권과 수집 gate | `universe.securities` |
| 과거 ticker/CUSIP/FIGI 연결 | `universe.security_identifiers` |
| 날짜별 S&P 500 구성 | `universe.memberships` (`tickers` JSONB) |
| 관심 기업 | `universe.entities.watchlist_sources` (발행사 행의 상태) |

모든 하류 market writer는 ticker를 입력으로 받지만 저장 직전에 `security_id`로
변환한다. `securities.is_tracked`가 현재 수집 gate이며 membership snapshot을
오늘 수집할 ticker의 gate로만 사용한다. 따라서 `historical backtest의 universe로 대체할 수`
없고, 하류 Python reader는 `select_security_profiles()`를 통해 entity를 조인한다.

## 실행 흐름

```text
SEC exchange master → entities seed + securities
SEC submissions    → entities metadata/freshness
S&P 500 목록       → memberships append + is_tracked reconcile
Toss(로컬 전용)    → entities.company_name_ko 보강
```

진입점은 다음과 같다.

```powershell
python -m investment_agent.data.universe.commands.universe_monthly
python -m investment_agent.data.universe.commands.universe_membership
python -m investment_agent.data.universe.commands.universe_names --retry-after-days 30
```

월간·membership entrypoint는 `collection.py`를 통해서만 저장소를 호출한다.
`persistence.py`는 운영 실행에 필요한 조합을 제공하지만 실제 표·페이지네이션·
identity 규칙은 `repository.py`와 `platform/db.py`가 소유한다.

## 안전 규칙

- `memberships`는 `index_code,effective_date`를 기준으로 append/upsert하고 hash와
  member count를 함께 검증한다.
- SEC 일시 실패는 저장하지 않고 실행을 실패시켜 다음 수집에서 재시도한다.
- `source_not_classified`는 정상 응답의 원천 결과이며 네트워크 실패와 구분한다.
- CIK 승계는 `verified`인 행만 entity 후보 확장에 사용한다.
- DB 초기화·재수집은 운영 runbook의 명시적 cutover 절차에서만 수행한다.

스키마의 단일 선언은 `db/postgres/v1/10_universe.sql`이며, bootstrap은 이 파일을 사용한다.
