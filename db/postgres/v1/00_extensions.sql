-- v1 공통 확장과 규약.
--
-- 이 파일은 스키마보다 먼저 한 번 적용된다. 여기서만 확장을 선언하고, 각 스키마
-- 파일은 확장이 이미 있다고 가정한다.

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;
-- 식별자 매핑의 기간 겹침을 EXCLUDE 제약으로 막는 데 쓴다(text = 연산의 gist 지원).
CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA extensions;

-- v1 전체가 지키는 규약 (각 스키마 파일에서 반복하지 않는다):
--
--   1. 시각 컬럼은 timestamptz. 날짜 경계가 사실인 것(거래일·회계기간말·발표일)만 date.
--   2. `_at`은 시각, `_date`는 날짜. 원천이 말하는 시점(`as_of`·`effective_at`)과 우리가
--      알게 된 시점(`available_at`·`collected_at`)을 한 컬럼에 섞지 않는다 — 섞으면 PIT
--      조회가 조용히 미래를 본다.
--   3. 모든 표는 RLS를 켜고 service_role에게만 권한을 준다. 이 DB를 읽는 클라이언트는
--      전부 service key를 쓰고, 관심·보유 종목 같은 개인 설정이 섞여 있으므로 anon·
--      authenticated에는 아무것도 열지 않는다.
--   4. 사실을 덮어쓰지 않는다. 값이 바뀌는 것이 정보인 표는 버전 행을 쌓고, 같은 상태가
--      반복되면 새 행 대신 `last_seen_at`만 옮긴다.
--   5. 파생값은 저장하지 않는다. 사람이 읽는 조합은 reporting 뷰가 만든다.
--   6. 표·컬럼마다 한국어 COMMENT로 "한 행의 뜻·단위·시간·NULL의 뜻"을 적는다.
