-- v1 공통 확장과 규약.
--
-- 이 파일은 스키마보다 먼저 한 번 적용된다. 여기서만 확장을 선언하고, 각 스키마
-- 파일은 확장이 이미 있다고 가정한다.

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;

-- v1 전체가 지키는 규약 (각 스키마 파일에서 반복하지 않는다):
--
--   1. 시각 컬럼은 timestamptz. 날짜 경계가 사실인 것(거래일·회계기간말·발표일)만 date.
--   2. `_at`은 시각, `_date`는 날짜. 관측 시점(`as_of`)과 우리가 알게 된 시점
--      (`available_at`/`collected_at`)을 절대 한 컬럼에 섞지 않는다 — 섞으면 PIT 조회가
--      조용히 미래를 본다.
--   3. 모든 표는 RLS를 켜고 anon/authenticated에는 SELECT만 준다. 쓰기는 service_role.
--   4. 사실을 덮어쓰지 않는다. 값이 바뀌는 것이 정보인 표는 `*_versions`로 append한다.
--   5. 파생값은 저장하지 않는다. 저장 형태가 아니라 내용으로 이름 짓는다.
