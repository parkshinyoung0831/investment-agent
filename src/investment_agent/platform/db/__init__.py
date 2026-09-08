"""저장 기술별 연결 경계. 각 파일이 하나의 DB만 안다.

이 패키지는 재수출하지 않는다. `platform.db`만 적으면 세 저장소 중 무엇을 여는지
이름이 말하지 않고, Supabase를 열려던 자리에서 로컬 SQLite를 열어도 import는
성공한다. 부르는 쪽이 `db.postgres` · `db.duckdb` · `db.sqlite`를 명시한다.

여기에는 표 이름이 없다. 어떤 표가 있는지는 `db/postgres/v1/*.sql`,
`db/duckdb/*/v1/*.sql`, `db/sqlite/runtime/v1/*.sql` 선언이 소유한다.
"""
from __future__ import annotations
