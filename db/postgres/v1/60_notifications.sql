-- notifications — 사람에게 알린 사실의 원장.
--
-- "이 소식을 이미 보냈나"는 로컬 하네스와 GitHub Actions가 함께 판단한다. 판단하는
-- 기계가 여럿이므로 원장은 실행 컴퓨터가 아니라 공유 DB 하나에 있어야 한다 — 기계마다
-- 원장을 두면 각자 "미발송"을 읽고 같은 카드를 한 번씩 보낸다.
--
-- 알림 하나의 정체성은 (topic, subject, occurrence)다. revision은 표시 내용의 hash라서
-- 같은 정체성의 내용이 바뀌었는지만 말한다. 전송·재시도·정정의 판단은 아래 함수들이
-- 서버 시각으로 원자적으로 내린다. Supabase에 닿지 못하면 보내지 않는다(fail-closed) —
-- 미발송은 다음 실행이 회복하지만 중복 발송은 되돌릴 수 없다.

CREATE SCHEMA IF NOT EXISTS notifications;
REVOKE ALL ON SCHEMA notifications FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA notifications TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA notifications REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA notifications GRANT ALL ON TABLES TO service_role;
-- deliveries의 identity 열이 쓰는 시퀀스. 표 권한만으로는 시도 기록을 넣지 못할 수 있다.
ALTER DEFAULT PRIVILEGES IN SCHEMA notifications GRANT USAGE, SELECT ON SEQUENCES TO service_role;

-- topic마다 원장이 책임지기 시작한 시각. 이보다 앞선 사실(fact_at)은 보내지 않고
-- suppressed로만 남긴다. 행이 없는 topic은 reserve가 거절한다 — 원장이 비었을 때
-- 과거 사실이 한꺼번에 "새 소식"이 되어 나가는 것을 막는 문이다.
CREATE TABLE IF NOT EXISTS notifications.topics (
  topic       text PRIMARY KEY CHECK (topic ~ '^[a-z]+(\.[a-z_]+)+$'),
  baseline_at timestamptz NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS notifications.notices (
  topic         text NOT NULL REFERENCES notifications.topics(topic) ON DELETE RESTRICT,
  subject       text NOT NULL CHECK (btrim(subject) <> '' AND length(subject) <= 200),
  occurrence    text NOT NULL CHECK (btrim(occurrence) <> '' AND length(occurrence) <= 400),
  revision      text NOT NULL CHECK (revision ~ '^[0-9a-f]{64}$'),
  -- 알린 사실이 일어난 시각(공시 접수·발표·관측일). baseline 판단에만 쓴다.
  fact_at       timestamptz NOT NULL,
  -- reserved: 이 실행이 준비 중 / sending: 전송 호출 직전 — 만료돼도 자동으로 다시 잡지 않는다.
  status        text NOT NULL CHECK (status IN ('reserved', 'sending', 'sent', 'failed', 'abandoned', 'unknown', 'suppressed')),
  attempts      smallint NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  owner         text CHECK (owner IS NULL OR btrim(owner) <> ''),
  lease_until   timestamptz,
  retry_at      timestamptz,
  -- 메시지가 사는 채널 또는 포럼 스레드. 수정할 때 이 둘이 필요하다.
  location_id   text CHECK (location_id IS NULL OR location_id ~ '^[0-9]{1,20}$'),
  message_id    text CHECK (message_id IS NULL OR message_id ~ '^[0-9]{1,20}$'),
  -- 사람이 마지막으로 받은 내용. revision과 다르면 정정할 거리가 있다.
  sent_revision text CHECK (sent_revision IS NULL OR sent_revision ~ '^[0-9a-f]{64}$'),
  failure_code  text,
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (topic, subject, occurrence),
  CONSTRAINT notices_lease_check CHECK (
    (status IN ('reserved', 'sending')) = (owner IS NOT NULL AND lease_until IS NOT NULL)
  ),
  CONSTRAINT notices_sent_location_check CHECK (
    status <> 'sent' OR (location_id IS NOT NULL AND message_id IS NOT NULL AND sent_revision IS NOT NULL)
  )
);
CREATE INDEX IF NOT EXISTS notices_topic_status_idx ON notifications.notices (topic, status);
CREATE INDEX IF NOT EXISTS notices_attention_idx ON notifications.notices (updated_at)
  WHERE status IN ('failed', 'abandoned', 'unknown', 'sending');

-- 시도 기록. 원장 행은 마지막 결과만 갖고, 무엇을 언제 시도했는지는 여기 남는다.
CREATE TABLE IF NOT EXISTS notifications.deliveries (
  delivery_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  topic        text NOT NULL,
  subject      text NOT NULL,
  occurrence   text NOT NULL,
  action       text NOT NULL CHECK (action IN ('create', 'edit', 'suppress')),
  outcome      text NOT NULL CHECK (outcome IN ('sent', 'failed', 'abandoned', 'unknown', 'suppressed')),
  revision     text NOT NULL CHECK (revision ~ '^[0-9a-f]{64}$'),
  location_id  text CHECK (location_id IS NULL OR location_id ~ '^[0-9]{1,20}$'),
  message_id   text CHECK (message_id IS NULL OR message_id ~ '^[0-9]{1,20}$'),
  failure_code text,
  attempted_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (topic, subject, occurrence)
    REFERENCES notifications.notices (topic, subject, occurrence) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS deliveries_notice_idx
  ON notifications.deliveries (topic, subject, occurrence, attempted_at DESC);

-- 포럼 스레드의 정체성. 제목 문자열과 Discord 목록 조회에 기대면 표시명이 바뀌거나
-- 보관 스레드가 목록 한 페이지를 넘길 때 같은 대상의 스레드가 둘로 갈라진다.
CREATE TABLE IF NOT EXISTS notifications.threads (
  channel_id text NOT NULL CHECK (channel_id ~ '^[0-9]{1,20}$'),
  thread_key text NOT NULL CHECK (btrim(thread_key) <> '' AND length(thread_key) <= 100),
  thread_id  text NOT NULL CHECK (thread_id ~ '^[0-9]{1,20}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (channel_id, thread_key)
);

ALTER TABLE notifications.topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications.notices ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications.deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications.threads ENABLE ROW LEVEL SECURITY;


-- 보낼 차례인 알림을 이 실행 몫으로 잡는다.
--
-- p_items: [{subject, occurrence, revision, fact_at}]
-- 돌려주는 action
--   create     처음 보내거나(새 알림·예약된 재시도·버려진 준비) 메시지가 아직 없다
--   edit       이미 보낸 메시지의 내용이 바뀌었다(p_revisable일 때만)
--   suppressed baseline 이전 사실이라 보내지 않고 기록만 했다
-- 잡지 못한 알림(다른 실행이 준비·전송 중, 이미 보냄, 결과 불명·포기)은 돌려주지 않는다.
CREATE OR REPLACE FUNCTION notifications.reserve(
  p_topic text,
  p_items jsonb,
  p_owner text,
  p_lease_seconds int,
  p_revisable boolean
)
RETURNS TABLE (subject text, occurrence text, action text, location_id text, message_id text, attempts integer)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $fn$
#variable_conflict use_column
DECLARE
  v_now timestamptz := pg_catalog.now();
  v_baseline timestamptz;
  v_lease timestamptz;
  v_item jsonb;
  v_subject text;
  v_occurrence text;
  v_revision text;
  v_fact_at timestamptz;
  v_inserted notifications.notices%ROWTYPE;
  v_updated notifications.notices%ROWTYPE;
BEGIN
  IF p_owner IS NULL OR pg_catalog.btrim(p_owner) = '' THEN
    RAISE EXCEPTION 'reserve requires an owner';
  END IF;
  IF p_lease_seconds IS NULL OR p_lease_seconds < 30 OR p_lease_seconds > 3600 THEN
    RAISE EXCEPTION 'reserve lease must be between 30 and 3600 seconds';
  END IF;
  IF p_items IS NULL OR pg_catalog.jsonb_typeof(p_items) <> 'array' THEN
    RAISE EXCEPTION 'reserve items must be a json array';
  END IF;
  SELECT t.baseline_at INTO v_baseline FROM notifications.topics t WHERE t.topic = p_topic;
  IF v_baseline IS NULL THEN
    RAISE EXCEPTION 'notification topic % has no baseline', p_topic;
  END IF;
  v_lease := v_now + pg_catalog.make_interval(secs => p_lease_seconds);

  FOR v_item IN SELECT value FROM pg_catalog.jsonb_array_elements(p_items) LOOP
    v_subject := v_item->>'subject';
    v_occurrence := v_item->>'occurrence';
    v_revision := v_item->>'revision';
    v_fact_at := (v_item->>'fact_at')::timestamptz;

    INSERT INTO notifications.notices AS n (
      topic, subject, occurrence, revision, fact_at, status, owner, lease_until, first_seen_at, updated_at
    )
    VALUES (
      p_topic, v_subject, v_occurrence, v_revision, v_fact_at,
      CASE WHEN v_fact_at < v_baseline THEN 'suppressed' ELSE 'reserved' END,
      CASE WHEN v_fact_at < v_baseline THEN NULL ELSE p_owner END,
      CASE WHEN v_fact_at < v_baseline THEN NULL ELSE v_lease END,
      v_now, v_now
    )
    ON CONFLICT ON CONSTRAINT notices_pkey DO NOTHING
    RETURNING n.* INTO v_inserted;

    IF FOUND THEN
      IF v_inserted.status = 'suppressed' THEN
        INSERT INTO notifications.deliveries (topic, subject, occurrence, action, outcome, revision)
        VALUES (p_topic, v_subject, v_occurrence, 'suppress', 'suppressed', v_revision);
        RETURN QUERY SELECT v_subject, v_occurrence, 'suppressed'::text, NULL::text, NULL::text, 0;
      ELSE
        RETURN QUERY SELECT v_subject, v_occurrence, 'create'::text, NULL::text, NULL::text, 0;
      END IF;
      CONTINUE;
    END IF;

    UPDATE notifications.notices AS n
    SET status = 'reserved', owner = p_owner, lease_until = v_lease,
        revision = v_revision, updated_at = v_now
    WHERE n.topic = p_topic AND n.subject = v_subject AND n.occurrence = v_occurrence
      AND (
        (n.status = 'reserved' AND n.lease_until < v_now)
        OR (n.status = 'failed' AND (n.retry_at IS NULL OR n.retry_at <= v_now))
        OR (p_revisable AND n.status = 'sent' AND n.sent_revision IS DISTINCT FROM v_revision)
        OR (p_revisable AND n.status = 'suppressed' AND n.revision IS DISTINCT FROM v_revision)
      )
    RETURNING n.* INTO v_updated;

    IF FOUND THEN
      RETURN QUERY SELECT v_subject, v_occurrence,
        CASE WHEN v_updated.message_id IS NULL THEN 'create' ELSE 'edit' END,
        v_updated.location_id, v_updated.message_id, v_updated.attempts::integer;
    ELSE
      -- 정정하지 않는 topic은 바뀐 내용을 기록만 한다. 다음 비교의 기준이 된다.
      UPDATE notifications.notices AS n
      SET revision = v_revision, updated_at = v_now
      WHERE n.topic = p_topic AND n.subject = v_subject AND n.occurrence = v_occurrence
        AND NOT p_revisable AND n.status IN ('sent', 'suppressed')
        AND n.revision IS DISTINCT FROM v_revision;
    END IF;
  END LOOP;
END $fn$;


-- 잡은 알림을 전송 직전 상태로 넘긴다. 이 실행의 예약이 살아 있는 행만 넘어간다.
-- 넘긴 개수가 요청과 다르면 호출자는 보내지 않는다 — 예약이 만료돼 다른 실행이
-- 가져갔을 수 있다.
CREATE OR REPLACE FUNCTION notifications.begin_send(p_topic text, p_keys jsonb, p_owner text)
RETURNS integer
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE
  v_now timestamptz := pg_catalog.now();
  v_count integer;
BEGIN
  UPDATE notifications.notices AS n
  SET status = 'sending', updated_at = v_now
  FROM pg_catalog.jsonb_to_recordset(p_keys) AS k(subject text, occurrence text)
  WHERE n.topic = p_topic AND n.subject = k.subject AND n.occurrence = k.occurrence
    AND n.owner = p_owner AND n.status = 'reserved' AND n.lease_until >= v_now;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END $fn$;


-- 한 번의 시도 결과를 기록한다. 이 실행이 잡은 행만 바뀐다.
CREATE OR REPLACE FUNCTION notifications.finish(
  p_topic text,
  p_keys jsonb,
  p_owner text,
  p_action text,
  p_outcome text,
  p_location_id text,
  p_message_id text,
  p_failure_code text,
  p_retry_seconds int
)
RETURNS integer
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE
  v_now timestamptz := pg_catalog.now();
  v_count integer;
BEGIN
  IF p_action NOT IN ('create', 'edit') THEN
    RAISE EXCEPTION 'finish action must be create or edit';
  END IF;
  IF p_outcome NOT IN ('sent', 'failed', 'abandoned', 'unknown') THEN
    RAISE EXCEPTION 'finish outcome must be sent, failed, abandoned or unknown';
  END IF;

  WITH updated AS (
    UPDATE notifications.notices AS n
    SET status = p_outcome,
        owner = NULL,
        lease_until = NULL,
        attempts = n.attempts + 1,
        retry_at = CASE WHEN p_outcome = 'failed'
                        THEN v_now + pg_catalog.make_interval(secs => GREATEST(COALESCE(p_retry_seconds, 60), 1))
                        END,
        location_id = COALESCE(p_location_id, n.location_id),
        message_id = COALESCE(p_message_id, n.message_id),
        sent_revision = CASE WHEN p_outcome = 'sent' THEN n.revision ELSE n.sent_revision END,
        failure_code = CASE WHEN p_outcome = 'sent' THEN NULL ELSE p_failure_code END,
        updated_at = v_now
    FROM pg_catalog.jsonb_to_recordset(p_keys) AS k(subject text, occurrence text)
    WHERE n.topic = p_topic AND n.subject = k.subject AND n.occurrence = k.occurrence
      AND n.owner = p_owner AND n.status IN ('reserved', 'sending')
    RETURNING n.topic, n.subject, n.occurrence, n.revision, n.location_id, n.message_id
  ), logged AS (
    INSERT INTO notifications.deliveries (
      topic, subject, occurrence, action, outcome, revision, location_id, message_id, failure_code
    )
    SELECT u.topic, u.subject, u.occurrence, p_action, p_outcome, u.revision,
           u.location_id, u.message_id, CASE WHEN p_outcome = 'sent' THEN NULL ELSE p_failure_code END
    FROM updated u
    RETURNING 1
  )
  SELECT count(*) INTO v_count FROM logged;
  RETURN v_count;
END $fn$;


-- 사람이 결정한 재발송. 다음 실행이 이 알림을 다시 잡는다 — 메시지가 있으면 같은
-- 메시지를 다시 그려 수정하고, 없으면(억제·포기·불명) 새로 보낸다.
CREATE OR REPLACE FUNCTION notifications.replay(p_topic text, p_subject text, p_occurrence text)
RETURNS integer
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE
  v_count integer;
BEGIN
  UPDATE notifications.notices AS n
  SET status = 'failed', retry_at = pg_catalog.now(), owner = NULL, lease_until = NULL,
      updated_at = pg_catalog.now()
  WHERE n.topic = p_topic AND n.subject = p_subject AND n.occurrence = p_occurrence
    AND n.status IN ('sent', 'suppressed', 'abandoned', 'unknown', 'sending');
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END $fn$;

REVOKE ALL ON FUNCTION notifications.reserve(text, jsonb, text, int, boolean) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION notifications.begin_send(text, jsonb, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION notifications.finish(text, jsonb, text, text, text, text, text, text, int) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION notifications.replay(text, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION notifications.reserve(text, jsonb, text, int, boolean) TO service_role;
GRANT EXECUTE ON FUNCTION notifications.begin_send(text, jsonb, text) TO service_role;
GRANT EXECUTE ON FUNCTION notifications.finish(text, jsonb, text, text, text, text, text, text, int) TO service_role;
GRANT EXECUTE ON FUNCTION notifications.replay(text, text, text) TO service_role;
