-- 관심 기업 seed: S&P 500 핵심 대표 50곳 (manual 출처).
--
-- db/postgres/v1 밖에 두는 이유: v1은 빈 DB에 한 트랜잭션으로 서는 선언만 갖는다
-- (tests/test_postgres_schema_layout.py). 이 seed는 수집된 universe.securities 행이
-- 있어야 하고 "누구를 관심 있게 보는가"는 개인 정보라 스키마 설치와 섞지 않는다.
-- 설치기(db_bootstrap)는 이 파일을 실행하지 않는다 — universe가 채워진 뒤 수동으로 한 번.
--
-- 멱등이다. 다시 돌려도 같은 결과이고 toss 출처와 이미 정한 watch_from은 건드리지 않는다.
-- 저장 키는 종목이 아니라 발행사 CIK다: GOOGL은 GOOG와 같은 회사라 한 곳으로 합쳐지고,
-- BRK.B는 universe 표기인 BRK-B로 적는다.
--
-- 적용 후 확인:
--   SELECT count(*) FROM universe.entities WHERE 'manual' = ANY(watchlist_sources);  -- 50
-- 시작일을 과거로 당겨 밀린 공시를 받으려면:
--   python -m investment_agent.data.universe.watchlists.watchlist watch-from YYYY-MM-DD

DO $seed$
DECLARE
  v_wanted  text[] := ARRAY[
    -- 빅테크 & 플랫폼·미디어
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NFLX', 'DIS',
    -- 반도체 & 하드웨어 인프라
    'NVDA', 'AVGO', 'QCOM', 'AMD', 'TXN', 'AMAT',
    -- 소프트웨어 & 클라우드 네트워크
    'ORCL', 'CRM', 'ADBE', 'CSCO',
    -- 필수소비재 & 대형 유통
    'KO', 'PEP', 'PG', 'WMT', 'COST', 'MDLZ',
    -- 자유소비재 & 외식·모빌리티
    'TSLA', 'MCD', 'SBUX', 'NKE', 'HD',
    -- 금융 & 결제 인프라
    'BRK-B', 'JPM', 'V', 'MA', 'BAC', 'GS', 'MS',
    -- 헬스케어 & 제약·바이오
    'LLY', 'UNH', 'JNJ', 'ABBV', 'MRK', 'TMO', 'ABT',
    -- 에너지 & 정유
    'XOM', 'CVX', 'COP',
    -- 산업재 & 방산·항공우주
    'CAT', 'GE', 'LMT', 'BA', 'UNP'
  ];
  v_missing text[];
  v_ciks    integer;
  v_updated integer;
BEGIN
  -- 상장 중이고 추적 중인 종목이 아니면 관심 기업으로 받지 않는다(watchlists.db._cik과 같은 기준).
  -- ticker는 자리표시 종목과 겹칠 수 있어 is_active_listing으로 좁힌다.
  SELECT array_agg(w ORDER BY w) INTO v_missing
  FROM unnest(v_wanted) AS w
  WHERE NOT EXISTS (
    SELECT 1 FROM universe.securities s
    WHERE s.ticker = w AND s.is_active_listing AND s.is_tracked AND s.cik IS NOT NULL
  );
  IF v_missing IS NOT NULL THEN
    RAISE EXCEPTION 'watchlist seed: 추적 중인 상장 종목이 아닌 ticker %', v_missing;
  END IF;

  SELECT count(DISTINCT s.cik) INTO v_ciks
  FROM universe.securities s
  WHERE s.ticker = ANY (v_wanted) AND s.is_active_listing AND s.is_tracked;

  UPDATE universe.entities e
  SET watchlist_sources    = ARRAY(SELECT DISTINCT x FROM unnest(e.watchlist_sources || 'manual'::text) AS x ORDER BY x),
      watch_from           = COALESCE(e.watch_from, current_date),
      watchlist_removed_at = NULL
  WHERE e.cik IN (
    SELECT s.cik FROM universe.securities s
    WHERE s.ticker = ANY (v_wanted) AND s.is_active_listing AND s.is_tracked
  );
  GET DIAGNOSTICS v_updated = ROW_COUNT;

  -- 0행 UPDATE는 오류 없이 지나간다. 회사 행이 빠진 CIK가 있으면 여기서 멈춘다.
  IF v_updated <> v_ciks THEN
    RAISE EXCEPTION 'watchlist seed: 회사 %곳 중 %곳만 universe.entities에 있다', v_ciks, v_updated;
  END IF;
END
$seed$;
