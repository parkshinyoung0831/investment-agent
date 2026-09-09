# Institutional — SEC 13F 원천·유효 포트폴리오

`investment_agent.data.institutional`은 SEC 13F-HR/13F-HR/A 원문을 수집해
공시 시점에 실제로 알려진 기관 보유를 복원한다. 13F는 분기말에서 최대 45일 늦게
공개되므로 PIT 조회의 경계는 `accepted_at`이다.

## 구조

```text
SEC EDGAR → parser → institutional.filings + institutional.positions
                         ├─ holdings.effective_filings (정정 규칙)
                         └─ universe.security_identifiers (CUSIP/CINS 매핑)
```

v1의 원천 테이블은 `db/postgres/v1/50_institutional.sql`이 선언한다.

| 테이블 | 역할 |
|---|---|
| `institutional.filings` | immutable SEC provenance, `accepted_at`, 정정 유형·해시 |
| `institutional.positions` | 원시 information-table 행과 수량·가치·옵션 정보 |

추적 대상 CIK와 운영 메타데이터(name/fund_name/is_active)는 Supabase 표가 아니라
`investment_agent.data.institutional.managers.MANAGER_CATALOG`가 SSOT다 —
manager는 SEC 사실이 아니라 우리가 고른 추적 대상이기 때문이다.

CUSIP/CINS 매핑은 `universe.security_identifiers`가 소유한다. 변화량·컨센서스 같은
read model은 `src/investment_agent/reporting/`에서 별도로 제공한다.

## 정확성 규칙

- RESTATEMENT는 해당 분기의 원본을 대체하고 NEW HOLDINGS는 기준 장부에 추가한다.
- SEC 원시 행을 Python에서 임의로 합치지 않아 sub-manager·의결권 정보를 보존한다.
- `SHARES`, `PUT`, `CALL`, `PRN`을 구분하며, 주식 신호는 long equity만 사용한다.
- 직접 XML parser가 production source of truth이고 EdgarTools는 선택적 shadow 감사다.
- API 장애는 매핑 결론으로 저장하지 않는다. `mapped`, `not_found`, `ambiguous`,
  `historical`만 `universe.security_identifiers`에 남긴다.

## 실행

```bash
python -m investment_agent.data.institutional.commands.institutional_daily --lookback-days 7
python -m investment_agent.data.institutional.commands.institutional_backfill
python -m investment_agent.data.institutional.commands.institutional_backfill --backfill-from 2020-01-01
GURUS_SHADOW_PARSER=on python -m investment_agent.data.institutional.commands.institutional_backfill --backfill-from 2014-01-01
```

백필은 과거 Discord 알림을 재발송하지 않는다. 개별 filing 실패는 성공한 accession의
적재를 보존하고 로그에 남긴다.

13F는 공개 롱 포지션의 지연된 일부일 뿐 숏·사모·해외 직접보유·현금을 보여주지 않는다.
따라서 매수 추천이 아니라 시점 보정된 리서치·피처 입력으로만 사용한다.

## 거장을 한 명 늘리려면

`domain/managers.py`의 `MANAGER_CATALOG`(SEC 사실)와 `MANAGER_PRESENTATION`(표시·해석)에
각각 한 줄을 넣는다. **그게 전부다.**

- Discord 채널 이름과 설명은 `name_ko`·`fund_name_ko`에서 파생된다
  (`guru_channels()`). `discord_admin` 선언도 이 함수에서 만들어진다.
- 채널 ID는 아무 데도 적지 않는다 — 봇이 길드에서 그 이름으로 찾는다
  (`notifications/channels/directory.py`).
- 운영 감시 목록(`operations/monitoring/channels.py`)도 같은 함수에서 나오므로,
  새 거장의 채널이 조용해지면 하트비트가 함께 묻는다.

`discord_admin` sync를 한 번 돌려 채널을 실제로 만들어야 카드가 그 포럼으로 간다.
아직 없으면 요약 채널(`13f-요약`)로 떨어지고 그 이유가 로그에 남는다.
